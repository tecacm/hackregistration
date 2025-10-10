from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from friends.matchmaking import MatchmakingService
from friends.models import (
	FriendsCode,
	FriendsMergeEventLog,
	FriendsMergePoolEntry,
	FriendsMembershipLog,
	get_random_string,
)
from friends.forms import (
	MatchmakingInviteForm,
	MatchmakingRunForm,
	TeamMembershipAddForm,
	TeamMembershipRemoveForm,
)


@admin.register(FriendsCode)
class FriendsCodeAdmin(admin.ModelAdmin):
	list_display = ('code', 'user', 'seeking_merge', 'seeking_merge_updated_at', 'track_assigned')
	search_fields = ('code', 'user__email', 'user__first_name', 'user__last_name')
	list_filter = ('seeking_merge', 'track_assigned')
	readonly_fields = ('seeking_merge_updated_at',)
	change_list_template = 'admin/friends/friendscode/change_list.html'

	def get_urls(self):
		urls = super().get_urls()
		custom = [
			path(
				'membership-manager/',
				self.admin_site.admin_view(self.membership_view),
				name='friends_friendscode_membership',
			),
		]
		return custom + urls

	def changelist_view(self, request, extra_context=None):
		extra_context = extra_context or {}
		extra_context['membership_url'] = reverse('admin:friends_friendscode_membership')
		return super().changelist_view(request, extra_context=extra_context)

	def membership_view(self, request):
		add_form = TeamMembershipAddForm(prefix='add')
		remove_form = TeamMembershipRemoveForm(prefix='remove')
		if request.method == 'POST':
			if 'add-submit' in request.POST:
				add_form = TeamMembershipAddForm(request.POST, prefix='add')
				if add_form.is_valid():
					self._handle_add(request, add_form.cleaned_data)
					return HttpResponseRedirect(request.path)
			elif 'remove-submit' in request.POST:
				remove_form = TeamMembershipRemoveForm(request.POST, prefix='remove')
				if remove_form.is_valid():
					self._handle_remove(request, remove_form.cleaned_data)
					return HttpResponseRedirect(request.path)

		context = dict(
			self.admin_site.each_context(request),
			title=_('Team membership manager'),
			add_form=add_form,
			remove_form=remove_form,
		)
		return TemplateResponse(request, 'admin/friends/team_membership.html', context)

	def _handle_add(self, request, cleaned_data):
		User = get_user_model()
		email = cleaned_data['email'].lower()
		team_code = cleaned_data.get('team_code') or ''
		move_if_exists = cleaned_data.get('move_if_exists', False)
		user = User.objects.filter(email__iexact=email).first()
		if user is None:
			messages.error(request, _('No user with email %(email)s was found.') % {'email': email})
			return

		existing_membership = FriendsCode.objects.filter(user=user).first()
		old_code = existing_membership.code if existing_membership else ''

		if existing_membership and not move_if_exists and (not team_code or team_code != existing_membership.code):
			messages.error(
				request,
				_('%(email)s already belongs to team %(code)s. Enable "move" to change their team.')
				% {'email': email, 'code': existing_membership.code},
			)
			return

		new_code = team_code
		if new_code:
			existing_team = FriendsCode.objects.filter(code=new_code)
			if not existing_team.exists():
				messages.error(request, _('Team %(code)s does not exist. Leave the field blank to create a new team.') % {'code': new_code})
				return
			# capacity check (ignore if user already part of target)
			friends_max_capacity = getattr(settings, 'FRIENDS_MAX_CAPACITY', None)
			if friends_max_capacity and friends_max_capacity > 0:
				current_size = existing_team.count()
				if (not existing_membership or existing_membership.code != new_code) and current_size >= friends_max_capacity:
					messages.error(request, _('Team %(code)s is already at capacity (%(cap)d).') % {'code': new_code, 'cap': friends_max_capacity})
					return
		else:
			new_code = self._generate_new_code()

		if existing_membership:
			if existing_membership.code == new_code:
				messages.info(request, _('%(email)s is already part of team %(code)s.') % {'email': email, 'code': new_code})
				return
			existing_membership.code = new_code
			existing_membership.save(update_fields=['code'])
			action = FriendsMembershipLog.ACTION_MOVE
		else:
			FriendsCode.objects.create(user=user, code=new_code)
			action = FriendsMembershipLog.ACTION_ADD

		FriendsMembershipLog.objects.create(
			admin_user=request.user,
			affected_user=user,
			action=action,
			from_code=old_code,
			to_code=new_code,
		)

		self._sync_merge_entries({code for code in [old_code, new_code] if code})
		messages.success(request, _('%(email)s is now in team %(code)s.') % {'email': email, 'code': new_code})

	def _handle_remove(self, request, cleaned_data):
		User = get_user_model()
		email = cleaned_data['email'].lower()
		user = User.objects.filter(email__iexact=email).first()
		if user is None:
			messages.error(request, _('No user with email %(email)s was found.') % {'email': email})
			return

		existing_membership = FriendsCode.objects.filter(user=user).first()
		if existing_membership is None:
			messages.error(request, _('%(email)s is not currently assigned to a team.') % {'email': email})
			return

		old_code = existing_membership.code
		existing_membership.delete()
		FriendsMembershipLog.objects.create(
			admin_user=request.user,
			affected_user=user,
			action=FriendsMembershipLog.ACTION_REMOVE,
			from_code=old_code,
		)
		self._sync_merge_entries({old_code})
		messages.success(request, _('%(email)s has been removed from team %(code)s.') % {'email': email, 'code': old_code})

	def _generate_new_code(self):
		while True:
			code = get_random_string()
			if not FriendsCode.objects.filter(code=code).exists():
				return code

	def _sync_merge_entries(self, team_codes):
		from friends.matchmaking import MatchmakingService
		for code in team_codes:
			entries = FriendsMergePoolEntry.objects.filter(team_code=code)
			if not entries.exists():
				continue
			for entry in entries:
				member_count = MatchmakingService._team_member_count(code, entry.edition)
				fields = ['member_count', 'updated_at']
				entry.member_count = member_count
				entry.updated_at = timezone.now()
				if member_count == 0 and entry.status == FriendsMergePoolEntry.STATUS_PENDING:
					entry.status = FriendsMergePoolEntry.STATUS_REMOVED
					entry.matched_team_code = ''
					entry.matched_at = None
					fields.extend(['status', 'matched_team_code', 'matched_at'])
					FriendsMergeEventLog.objects.create(
						entry=entry,
						event_type=FriendsMergeEventLog.EVENT_REMOVED,
						message='Removed after admin membership change.',
					)
					FriendsCode.objects.filter(code=code).update(seeking_merge=False)
				entry.save(update_fields=fields)


@admin.register(FriendsMembershipLog)
class FriendsMembershipLogAdmin(admin.ModelAdmin):
	list_display = ('timestamp', 'affected_user', 'action', 'from_code', 'to_code', 'admin_user')
	list_filter = ('action',)
	search_fields = ('affected_user__email', 'from_code', 'to_code')
	readonly_fields = ('timestamp',)


@admin.register(FriendsMergeEventLog)
class FriendsMergeEventLogAdmin(admin.ModelAdmin):
	list_display = ('created_at', 'entry', 'event_type', 'actor')
	list_filter = ('event_type',)
	search_fields = ('entry__team_code', 'actor__email')
	readonly_fields = ('created_at',)


@admin.register(FriendsMergePoolEntry)
class FriendsMergePoolEntryAdmin(admin.ModelAdmin):
	list_display = ('team_code', 'edition', 'member_count', 'status', 'trigger', 'matched_team_code', 'created_at')
	list_filter = ('status', 'trigger', 'edition')
	search_fields = ('team_code', 'matched_team_code')
	readonly_fields = ('created_at', 'updated_at', 'matched_at')
	actions = ('merge_selected', 'remove_from_pool')
	change_list_template = 'admin/friends/friendsmergepoolentry/change_list.html'

	def get_urls(self):
		urls = super().get_urls()
		custom_urls = [
			path(
				'matchmaking-control/',
				self.admin_site.admin_view(self.matchmaking_view),
				name='friends_friendsmergepoolentry_matchmaking',
			),
		]
		return custom_urls + urls

	def changelist_view(self, request, extra_context=None):
		extra_context = extra_context or {}
		extra_context['matchmaking_url'] = reverse('admin:friends_friendsmergepoolentry_matchmaking')
		return super().changelist_view(request, extra_context=extra_context)

	def matchmaking_view(self, request):
		default_edition = None
		try:
			default_edition = MatchmakingService.get_edition()
		except Exception:
			default_edition = None
		invite_initial = {'edition': default_edition.pk} if default_edition else {}
		match_initial = {'edition': default_edition.pk} if default_edition else {}
		invite_form = MatchmakingInviteForm(prefix='invite', initial=invite_initial)
		match_form = MatchmakingRunForm(prefix='match', initial=match_initial)
		invite_preview = None
		match_preview = None

		if request.method == 'POST':
			if 'invite-preview' in request.POST or 'invite-send' in request.POST:
				action = 'preview' if 'invite-preview' in request.POST else 'send'
				invite_form = MatchmakingInviteForm(request.POST, prefix='invite', initial=invite_initial)
				if invite_form.is_valid():
					try:
						edition = invite_form.cleaned_data['edition'] or MatchmakingService.get_edition()
						limit = invite_form.cleaned_data['limit']
						resend = invite_form.cleaned_data['resend']
						preview_email = invite_form.cleaned_data['preview_email']
						invites = MatchmakingService.gather_invite_targets(edition, include_existing=resend)
						if limit:
							invites = invites[:limit]
						if not invites:
							self.message_user(request, _('No eligible teams or solo applicants found.'), level=messages.WARNING)
						else:
							if preview_email:
								sample_invite = invites[0]
								MatchmakingService.send_invite(sample_invite, dry_run=False, override_emails=[preview_email])
								self.message_user(
									request,
									_('Preview invite sent to %(email)s using team %(team)s.') % {
										'email': preview_email,
										'team': sample_invite.team_code or _('solo applicant'),
									},
									level=messages.SUCCESS,
								)
							if action == 'preview':
								invite_preview = self._build_invite_preview(invites)
							else:
								sent = 0
								for invite in invites:
									MatchmakingService.send_invite(invite)
									sent += 1
								self.message_user(
									request,
									_('%(count)s invite(s) queued for delivery.') % {'count': sent},
									level=messages.SUCCESS,
								)
								return HttpResponseRedirect(request.path)
					except Exception as exc:
						self.message_user(request, _('Invite run failed: %(error)s') % {'error': exc}, level=messages.ERROR)
			elif 'match-preview' in request.POST:
				match_form = MatchmakingRunForm(request.POST, prefix='match', initial=match_initial)
				if match_form.is_valid():
					try:
						edition = match_form.cleaned_data['edition'] or MatchmakingService.get_edition()
						allow_size_three = match_form.cleaned_data['allow_size_three']
						trigger = match_form.cleaned_data['trigger']
						preview_data = MatchmakingService.build_match_preview(
							edition,
							allow_size_three=allow_size_three,
							trigger=trigger,
						)
						if preview_data:
							match_preview = preview_data
						else:
							self.message_user(
								request,
								_('No eligible matches are ready yet, so there is nothing to preview.'),
								level=messages.INFO,
							)
					except Exception as exc:
						self.message_user(request, _('Match preview failed: %(error)s') % {'error': exc}, level=messages.ERROR)
			elif 'match-submit' in request.POST:
				match_form = MatchmakingRunForm(request.POST, prefix='match', initial=match_initial)
				if match_form.is_valid():
					try:
						edition = match_form.cleaned_data['edition'] or MatchmakingService.get_edition()
						allow_size_three = match_form.cleaned_data['allow_size_three']
						trigger = match_form.cleaned_data['trigger']
						results = MatchmakingService.run_matching(
							edition,
							allow_size_three=allow_size_three,
							trigger=trigger,
						)
						if results:
							summary = ', '.join(
								f"{result.team_code} ({len(result.member_ids)} hackers)" for result in results[:5]
							)
							if len(results) > 5:
								summary += _(' (and %(count)s more merges)') % {'count': len(results) - 5}
							self.message_user(
								request,
								_('Matching run merged %(count)s group(s): %(summary)s') % {
									'count': len(results),
									'summary': summary,
								},
								level=messages.SUCCESS,
							)
						else:
							self.message_user(request, _('No matches were formed.'), level=messages.INFO)
					except Exception as exc:
						self.message_user(request, _('Matching run failed: %(error)s') % {'error': exc}, level=messages.ERROR)
					return HttpResponseRedirect(request.path)

		context = dict(
			self.admin_site.each_context(request),
			title=_('Matchmaking controls'),
			invite_form=invite_form,
			match_form=match_form,
			invite_preview=invite_preview,
			match_preview=match_preview,
		)
		return TemplateResponse(request, 'admin/friends/matchmaking_dashboard.html', context)

	def _build_invite_preview(self, invites):
		display_limit = 25
		groups = []
		total_recipients = 0
		for index, invite in enumerate(invites):
			members = []
			for app in invite.members:
				name = MatchmakingService._member_display_name(app)
				email = getattr(app.user, 'email', '')
				if email:
					total_recipients += 1
				members.append({'name': name, 'email': email})
			if index < display_limit:
				team_label = invite.team_code
				if not team_label:
					first_member = invite.members[0] if invite.members else None
					if first_member:
						team_label = _('Solo – %(name)s') % {'name': MatchmakingService._member_display_name(first_member)}
					else:
						team_label = _('Solo applicant')
				groups.append({
					'team_label': team_label,
					'member_count': len(invite.members),
					'members': members,
				})
		sample_email = None
		for invite in invites:
			for app in invite.members:
				target_email = getattr(app.user, 'email', '')
				if not target_email:
					continue
				email_obj = MatchmakingService.build_invite_email(
					invite,
					app,
					override_email=target_email,
					override_recipient_name=MatchmakingService._member_display_name(app),
				)
				if email_obj:
					sample_email = {
						'subject': email_obj.subject.strip(),
						'html': email_obj.html_message,
						'recipient': target_email,
						'recipient_name': MatchmakingService._member_display_name(app),
					}
					break
			if sample_email:
				break
		return {
			'total_groups': len(invites),
			'displayed_groups': len(groups),
			'hidden_group_count': max(len(invites) - display_limit, 0),
			'total_recipients': total_recipients,
			'recipient_groups': groups,
			'sample_email': sample_email,
			'display_limit': display_limit,
		}

	def merge_selected(self, request, queryset):
		entries = list(queryset.select_related('edition'))
		if not entries:
			self.message_user(request, 'Select at least one entry to merge.', level=messages.ERROR)
			return
		edition_ids = {entry.edition_id for entry in entries}
		if len(edition_ids) > 1:
			self.message_user(request, 'Please select entries from the same edition.', level=messages.ERROR)
			return
		total = sum(entry.member_count for entry in entries)
		if total < 3 or total > MatchmakingService.TARGET_TEAM_SIZE:
			self.message_user(request, 'Manual merges must total between 3 and 4 members.', level=messages.ERROR)
			return
		edition = entries[0].edition
		with transaction.atomic():
			result = MatchmakingService._merge_entries(entries, edition, FriendsMergePoolEntry.TRIGGER_MANUAL)  # type: ignore[attr-defined]
		if result:
			self.message_user(request, f'Merged into team {result.team_code}.', level=messages.SUCCESS)
		else:
			self.message_user(request, 'Merge aborted: one or more teams are no longer eligible.', level=messages.WARNING)

	merge_selected.short_description = 'Merge selected entries'

	def remove_from_pool(self, request, queryset):
		count = 0
		with transaction.atomic():
			for entry in queryset:
				entry.status = FriendsMergePoolEntry.STATUS_REMOVED
				entry.updated_at = timezone.now()
				entry.save(update_fields=['status', 'updated_at'])
				FriendsCode.objects.filter(code=entry.team_code).update(seeking_merge=False, seeking_merge_updated_at=timezone.now())
				FriendsMergeEventLog.objects.create(
					entry=entry,
					event_type=FriendsMergeEventLog.EVENT_REMOVED,
					message='Removed manually from admin.',
					actor=request.user,
				)
				count += 1
		self.message_user(request, f'Removed {count} entr{"y" if count == 1 else "ies"} from the pool.', level=messages.SUCCESS)

	remove_from_pool.short_description = 'Remove from pool (and reset seeking flag)'
