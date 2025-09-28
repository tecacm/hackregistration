from django.contrib import admin
from django.conf import settings
from django.utils.html import format_html
from django.db.models import Count
from django.db import connection
from django.http import HttpResponse
from django import forms
from django.contrib import messages
import csv

from friends.models import FriendsCode, FriendsMembershipLog
from application.models import Application, Edition


class MembersSizeFilter(admin.SimpleListFilter):
	title = 'Members size'
	parameter_name = 'members_size'

	def lookups(self, request, model_admin):
		cap = getattr(settings, 'FRIENDS_MAX_CAPACITY', 4) or 4
		return [(str(i), str(i)) for i in range(1, cap + 1)]

	def queryset(self, request, queryset):
		value = self.value()
		if not value:
			return queryset
		try:
			size = int(value)
		except ValueError:
			return queryset
		codes = FriendsCode.objects.values('code').annotate(cnt=Count('id')).filter(cnt=size).values_list('code', flat=True)
		return queryset.filter(code__in=list(codes))


class HasDevpostFilter(admin.SimpleListFilter):
	title = 'Has Devpost'
	parameter_name = 'has_devpost'

	def lookups(self, request, model_admin):
		return [('yes', 'Yes'), ('no', 'No')]

	def queryset(self, request, queryset):
		value = self.value()
		if value == 'yes':
			codes = FriendsCode.objects.exclude(devpost_url__isnull=True).exclude(devpost_url__exact='')\
				.values_list('code', flat=True).distinct()
			return queryset.filter(code__in=list(codes))
		if value == 'no':
			codes = FriendsCode.objects.exclude(devpost_url__isnull=True).exclude(devpost_url__exact='')\
				.values_list('code', flat=True).distinct()
			return queryset.exclude(code__in=list(codes))
		return queryset


class AnyInvitedConfirmedFilter(admin.SimpleListFilter):
	title = 'Any invited/confirmed'
	parameter_name = 'has_invited_confirmed'

	def lookups(self, request, model_admin):
		return [('yes', 'Yes'), ('no', 'No')]

	def queryset(self, request, queryset):
		value = self.value()
		if not value:
			return queryset
		edition = Edition.get_default_edition()
		codes = Application.objects.filter(
			user__friendscode__code__isnull=False,
			edition=edition,
			status__in=[Application.STATUS_INVITED, Application.STATUS_CONFIRMED]
		).values_list('user__friendscode__code', flat=True).distinct()
		if value == 'yes':
			return queryset.filter(code__in=list(codes))
		else:
			return queryset.exclude(code__in=list(codes))


@admin.register(FriendsCode)
class FriendsCodeAdmin(admin.ModelAdmin):
	list_display = (
		'code', 'members_count', 'capacity', 'pending_count', 'invited_count', 'confirmed_count', 'track_assigned', 'devpost_link',
	)
	search_fields = ('code', 'user__email', 'user__first_name', 'user__last_name')
	readonly_fields = ('code', 'members_count', 'capacity', 'devpost_link', 'members_list',
	                  'pending_count', 'invited_count', 'confirmed_count')
	fields = (
		'code', 'devpost_url', 'devpost_link', 'track_assigned',
		'members_count', 'capacity',
		'members_list',
	)
	list_filter = (MembersSizeFilter, HasDevpostFilter, AnyInvitedConfirmedFilter)
	actions = ('export_csv', 'open_invite_view', 'add_member_action', 'remove_selected_members', 'clear_track_assignment', 'reset_preferences')

	class AddMemberForm(forms.Form):
		email = forms.EmailField(required=True, help_text='Email of existing user to add to this team')
		force_move = forms.BooleanField(required=False, help_text='If user already in another team, move them here')

	def get_urls(self):
		from django.urls import path
		urls = super().get_urls()
		custom = [
			path('add-member/<str:code>/', self.admin_site.admin_view(self.add_member_view), name='friends_add_member'),
			path('remove-member/<str:code>/<int:member_id>/', self.admin_site.admin_view(self.remove_member_view), name='friends_remove_member'),
			path('assign-track/<str:code>/', self.admin_site.admin_view(self.assign_track_view), name='friends_assign_track'),
		]
		return custom + urls

	def add_member_view(self, request, code):
		from django.shortcuts import render, redirect
		team_qs = FriendsCode.objects.filter(code=code)
		if not team_qs.exists():
			messages.error(request, 'Team not found')
			return redirect('..')
		form = self.AddMemberForm(request.POST or None)
		if request.method == 'POST' and form.is_valid():
			from django.contrib.auth import get_user_model
			User = get_user_model()
			email = form.cleaned_data['email']
			force_move = form.cleaned_data.get('force_move')
			try:
				user = User.objects.get(email__iexact=email)
			except User.DoesNotExist:
				messages.error(request, 'User with that email does not exist.')
				return redirect(request.path)
			# Capacity check
			cap = getattr(settings, 'FRIENDS_MAX_CAPACITY', None)
			if cap and team_qs.count() >= cap:
				messages.error(request, 'Team is already at maximum capacity.')
				return redirect(request.path)
			# Ensure user not already in any team for this edition
			current = FriendsCode.objects.filter(user=user).first()
			if current and current.code != code:
				if not force_move:
					messages.error(request, 'User already on a team. Use force move to relocate.')
					return redirect(request.path)
				from friends.models import FriendsMembershipLog
				old_code = current.code
				FriendsCode.objects.filter(user=user).delete()
				FriendsCode.objects.create(user=user, code=code)
				FriendsMembershipLog.objects.create(admin_user=request.user, affected_user=user, action=FriendsMembershipLog.ACTION_MOVE, from_code=old_code, to_code=code)
				messages.success(request, f'Moved {user.email} from {old_code} to {code}.')
			else:
				FriendsCode.objects.create(user=user, code=code)
				from friends.models import FriendsMembershipLog
				FriendsMembershipLog.objects.create(admin_user=request.user, affected_user=user, action=FriendsMembershipLog.ACTION_ADD, to_code=code)
				messages.success(request, f'Added {user.email} to team {code}.')
			return redirect('../../')  # back to list
		context = dict(
			self.admin_site.each_context(request),
			form=form,
			team_code=code,
			team_members=team_qs.select_related('user'),
			title=f'Add member to team {code}'
		)
		return render(request, 'admin/friends/add_member.html', context)

	def remove_member_view(self, request, code, member_id):
		from django.shortcuts import redirect
		member = FriendsCode.objects.filter(code=code, id=member_id).select_related('user').first()
		if not member:
			messages.error(request, 'Member not found.')
			return redirect('../../')
			
		from friends.models import FriendsMembershipLog
		user = member.user
		member.delete()
		FriendsMembershipLog.objects.create(admin_user=request.user, affected_user=user, action=FriendsMembershipLog.ACTION_REMOVE, from_code=code)
		messages.success(request, f'Removed {user.email} from team {code}.')
		return redirect(f'../../../add-member/{code}/')

	def add_member_action(self, request, queryset):
		codes = list(queryset.values_list('code', flat=True).distinct())
		if len(codes) != 1:
			self.message_user(request, 'Select exactly one team to add a member.', level='error')
			return
		from django.urls import reverse
		url = reverse('admin:friends_add_member', args=[codes[0]])
		from django.shortcuts import redirect
		return redirect(url)

	add_member_action.short_description = 'Add member to selected team'

	def remove_selected_members(self, request, queryset):
		# queryset already limited to representative records; we need selected pks giving us a team code list
		codes = list(queryset.values_list('code', flat=True).distinct())
		removed = 0
		for code in codes:
			# Remove all members except one? Requirement: remove persons from a team – we'll delete selected representative teams entirely? Instead, show message.
			pass
		self.message_user(request, 'Use the per-team page to remove individual members (feature not implemented).', level='warning')

	remove_selected_members.short_description = 'Remove members (placeholder)'

	def clear_track_assignment(self, request, queryset):
		codes = list(queryset.values_list('code', flat=True).distinct())
		from django.utils import timezone
		count = FriendsCode.objects.filter(code__in=codes).update(track_assigned='', track_assigned_date=None)
		self.message_user(request, f'Cleared track assignment for {len(codes)} team(s). (Updated {count} rows)')

	clear_track_assignment.short_description = 'Clear track assignment for selected team(s)'

	def reset_preferences(self, request, queryset):
		codes = list(queryset.values_list('code', flat=True).distinct())
		count = FriendsCode.objects.filter(code__in=codes).update(track_pref_1='', track_pref_2='', track_pref_3='')
		self.message_user(request, f'Reset track preferences for {len(codes)} team(s). (Updated {count} rows)')

	reset_preferences.short_description = 'Reset track preferences for selected team(s)'

	class AssignTrackForm(forms.Form):
		track = forms.ChoiceField(choices=[('', '--- Select track ---')] + FriendsCode.TRACKS, required=False, help_text='Leave blank to clear assignment.')
		apply_to_all = forms.BooleanField(required=False, help_text='Apply to every member record of this team (recommended).')

	def assign_track_view(self, request, code):
		from django.shortcuts import render, redirect
		team_exists = FriendsCode.objects.filter(code=code).exists()
		if not team_exists:
			messages.error(request, 'Team not found.')
			return redirect('..')
		form = self.AssignTrackForm(request.POST or None, initial={'apply_to_all': True})
		if request.method == 'POST' and form.is_valid():
			track = form.cleaned_data['track'] or ''
			apply_all = form.cleaned_data['apply_to_all']
			qs = FriendsCode.objects.filter(code=code)
			from django.utils import timezone
			if track:
				qs.update(track_assigned=track, track_assigned_date=timezone.now())
				self.message_user(request, f'Track {track} assigned to team {code}.')
			else:
				qs.update(track_assigned='', track_assigned_date=None)
				self.message_user(request, f'Track assignment cleared for team {code}.')
			return redirect('../../')
		context = dict(
			self.admin_site.each_context(request),
			form=form,
			team_code=code,
			title=f'Assign/Clear Track for team {code}'
		)
		return render(request, 'admin/friends/assign_track.html', context)

	# ===================== GROUP METRIC / UTILITY METHODS (moved back into FriendsCodeAdmin) =====================

	def export_csv(self, request, queryset):
		# Aggregate unique codes
		codes = list(queryset.values_list('code', flat=True).distinct())
		edition = Edition.get_default_edition()
		response = HttpResponse(content_type='text/csv')
		response['Content-Disposition'] = 'attachment; filename=friends_groups.csv'
		writer = csv.writer(response)
		writer.writerow(['code', 'members', 'capacity', 'pending', 'invited', 'confirmed', 'devpost', 'members_emails'])
		for code in codes:
			members = FriendsCode.objects.filter(code=code).select_related('user')
			members_count = members.count()
			devpost = members.exclude(devpost_url__isnull=True).exclude(devpost_url__exact='')\
				.values_list('devpost_url', flat=True).first() or ''
			apps = Application.objects.filter(user__friendscode__code=code, edition=edition)
			pending = apps.filter(status=Application.STATUS_PENDING).count()
			invited = apps.filter(status=Application.STATUS_INVITED).count()
			confirmed = apps.filter(status=Application.STATUS_CONFIRMED).count()
			emails = ';'.join([m.user.email for m in members])
			writer.writerow([code, members_count, getattr(settings, 'FRIENDS_MAX_CAPACITY', None) or '',
						 	 pending, invited, confirmed, devpost, emails])
		return response

	export_csv.short_description = 'Export selected groups to CSV'

	def open_invite_view(self, request, queryset):
		codes = list(queryset.values_list('code', flat=True).distinct())
		from django.shortcuts import redirect
		if len(codes) != 1:
			self.message_user(request, 'Please select exactly one group to open the invite view.', level='error')
			return None
		url = f"/friends/invite/?code={codes[0]}"
		return redirect(url)

	open_invite_view.short_description = 'Open Invite friends view for selected group'

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		# Limit to one row per code (representative record)
		if getattr(connection.features, 'supports_distinct_on', False):
			return qs.order_by('code').distinct('code')
		# Fallback for backends without DISTINCT ON
		seen = set()
		ids = []
		for pk, code in qs.values_list('pk', 'code').order_by('code'):
			if code in seen:
				continue
			seen.add(code)
			ids.append(pk)
		return qs.filter(pk__in=ids)

	def _edition(self):
		return Edition.get_default_edition()

	def _group_qs(self, obj):
		return FriendsCode.objects.filter(code=obj.code)

	def members_count(self, obj):
		return self._group_qs(obj).count()

	members_count.short_description = 'Members'

	def capacity(self, obj):
		return getattr(settings, 'FRIENDS_MAX_CAPACITY', None)

	def _apps(self, obj):
		return Application.objects.filter(user__friendscode__code=obj.code, edition=self._edition())

	def pending_count(self, obj):
		return self._apps(obj).filter(status=Application.STATUS_PENDING).count()

	pending_count.short_description = 'Pending'

	def invited_count(self, obj):
		return self._apps(obj).filter(status=Application.STATUS_INVITED).count()

	invited_count.short_description = 'Invited'

	def confirmed_count(self, obj):
		return self._apps(obj).filter(status=Application.STATUS_CONFIRMED).count()

	confirmed_count.short_description = 'Confirmed'

	def devpost_link(self, obj):
		# Use the first non-empty url in the group
		url = self._group_qs(obj).exclude(devpost_url__isnull=True).exclude(devpost_url__exact='')\
			.values_list('devpost_url', flat=True).first()
		if not url:
			return '-'
		return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', url, url)

	devpost_link.short_description = 'Devpost'

	def members_list(self, obj):
		members = self._group_qs(obj).select_related('user')
		items = []
		for fc in members:
			items.append(f"{fc.user.get_full_name()} ({fc.user.email})")
		if not items:
			return '-'
		return format_html('<ul style="margin:0;padding-left:16px">{}</ul>',
					   format_html(''.join(f'<li>{item}</li>' for item in items)))

	members_list.short_description = 'Members'

	def get_list_display(self, request):
		return super().get_list_display(request)

	def get_search_results(self, request, queryset, search_term):
		qs, use_distinct = super().get_search_results(request, queryset, search_term)
		return qs, use_distinct

	def save_model(self, request, obj, form, change):
		# Save base object first
		super().save_model(request, obj, form, change)
		# Propagate Devpost URL and track assignment changes to all rows with same code
		update_fields = {'devpost_url': obj.devpost_url}
		if 'track_assigned' in form.changed_data:
			from django.utils import timezone
			if obj.track_assigned:
				update_fields['track_assigned'] = obj.track_assigned
				update_fields['track_assigned_date'] = timezone.now()
			else:
				# Clearing track: blank out date too
				update_fields['track_assigned'] = ''
				update_fields['track_assigned_date'] = None
		FriendsCode.objects.filter(code=obj.code).update(**update_fields)


@admin.register(FriendsMembershipLog)
class FriendsMembershipLogAdmin(admin.ModelAdmin):
	list_display = ('timestamp', 'admin_user', 'affected_user', 'action', 'from_code', 'to_code')
	list_filter = ('action', 'admin_user')
	search_fields = ('affected_user__email', 'from_code', 'to_code')
	readonly_fields = ('timestamp', 'admin_user', 'affected_user', 'action', 'from_code', 'to_code')
	def has_add_permission(self, request):
		return False
	def has_change_permission(self, request, obj=None):
		return False
	def has_delete_permission(self, request, obj=None):
		return False

	class MembersSizeFilter(admin.SimpleListFilter):
		title = 'Members size'
		parameter_name = 'members_size'

		def lookups(self, request, model_admin):
			cap = getattr(settings, 'FRIENDS_MAX_CAPACITY', 4) or 4
			return [(str(i), str(i)) for i in range(1, cap + 1)]

		def queryset(self, request, queryset):
			value = self.value()
			if not value:
				return queryset
			try:
				size = int(value)
			except ValueError:
				return queryset
			codes = FriendsCode.objects.values('code').annotate(cnt=Count('id')).filter(cnt=size).values_list('code', flat=True)
			return queryset.filter(code__in=list(codes))

	class HasDevpostFilter(admin.SimpleListFilter):
		title = 'Has Devpost'
		parameter_name = 'has_devpost'

		def lookups(self, request, model_admin):
			return [('yes', 'Yes'), ('no', 'No')]

		def queryset(self, request, queryset):
			value = self.value()
			if value == 'yes':
				codes = FriendsCode.objects.exclude(devpost_url__isnull=True).exclude(devpost_url__exact='')\
					.values_list('code', flat=True).distinct()
				return queryset.filter(code__in=list(codes))
			if value == 'no':
				codes = FriendsCode.objects.exclude(devpost_url__isnull=True).exclude(devpost_url__exact='')\
					.values_list('code', flat=True).distinct()
				return queryset.exclude(code__in=list(codes))
			return queryset

	class AnyInvitedConfirmedFilter(admin.SimpleListFilter):
		title = 'Any invited/confirmed'
		parameter_name = 'has_invited_confirmed'

		def lookups(self, request, model_admin):
			return [('yes', 'Yes'), ('no', 'No')]

		def queryset(self, request, queryset):
			value = self.value()
			if not value:
				return queryset
			edition = Edition.get_default_edition()
			codes = Application.objects.filter(
				user__friendscode__code__isnull=False,
				edition=edition,
				status__in=[Application.STATUS_INVITED, Application.STATUS_CONFIRMED]
			).values_list('user__friendscode__code', flat=True).distinct()
			if value == 'yes':
				return queryset.filter(code__in=list(codes))
			else:
				return queryset.exclude(code__in=list(codes))

	def export_csv(self, request, queryset):
		# Aggregate unique codes
		codes = list(queryset.values_list('code', flat=True).distinct())
		edition = Edition.get_default_edition()
		response = HttpResponse(content_type='text/csv')
		response['Content-Disposition'] = 'attachment; filename=friends_groups.csv'
		writer = csv.writer(response)
		writer.writerow(['code', 'members', 'capacity', 'pending', 'invited', 'confirmed', 'devpost', 'members_emails'])
		for code in codes:
			members = FriendsCode.objects.filter(code=code).select_related('user')
			members_count = members.count()
			devpost = members.exclude(devpost_url__isnull=True).exclude(devpost_url__exact='')\
				.values_list('devpost_url', flat=True).first() or ''
			apps = Application.objects.filter(user__friendscode__code=code, edition=edition)
			pending = apps.filter(status=Application.STATUS_PENDING).count()
			invited = apps.filter(status=Application.STATUS_INVITED).count()
			confirmed = apps.filter(status=Application.STATUS_CONFIRMED).count()
