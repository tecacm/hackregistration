from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.core import signing
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import get_fixed_timezone, is_naive, make_aware
from django.utils.translation import gettext_lazy as _

from app.emails import Email
from application.models import Application, Edition
from friends.models import (
	FriendsCode,
	FriendsMergeEventLog,
	FriendsMergePoolEntry,
)

TOKEN_SALT = 'friends.merge.optin'
TOKEN_MAX_AGE = getattr(settings, 'FRIENDS_MERGE_TOKEN_MAX_AGE', 7 * 24 * 3600)
TARGET_TEAM_SIZE = getattr(settings, 'FRIENDS_MAX_CAPACITY', 4) or 4
DEFAULT_DEADLINE = getattr(
	settings,
	'FRIENDS_MERGE_DEADLINE',
	datetime(2025, 10, 11, 18, 0, tzinfo=timezone.utc),
)

CONTACT_FIELD_CANDIDATES = {
	'phone': ('phone_number', 'phone', 'mobile', 'mobile_phone'),
	'university': ('university', 'college', 'school', 'institution'),
	'degree': ('degree', 'major', 'field_of_study', 'program'),
	'country': ('country_of_origin', 'country', 'nationality'),
}


@dataclass
class TeamInvite:
	edition: Edition
	token: str
	member_count: int
	team_code: Optional[str]
	members: List[Application]


@dataclass
class MatchGroupResult:
	team_code: str
	member_ids: List[int]
	trigger: str


class MatchmakingService:
	"""Utility helpers to power the friends merge workflow."""

	TARGET_TEAM_SIZE = TARGET_TEAM_SIZE

	@classmethod
	def get_edition(cls, edition: Optional[Edition | int] = None) -> Edition:
		if isinstance(edition, Edition):
			return edition
		if edition:
			return Edition.objects.get(pk=edition)
		return Edition.objects.get(pk=Edition.get_default_edition())

	@classmethod
	def _current_team_code(cls, user) -> Optional[str]:
		friend = FriendsCode.objects.filter(user=user).only('code').first()
		return friend.code if friend else None

	@classmethod
	def generate_opt_in_token(cls, user, edition: Edition, team_code: Optional[str]) -> str:
		payload = {
			'user_id': user.pk,
			'edition_id': edition.pk,
			'team_code': team_code or '',
			'ts': timezone.now().timestamp(),
		}
		return signing.dumps(payload, salt=TOKEN_SALT)

	@classmethod
	def build_accept_url(cls, token: str) -> str:
		path = reverse('friends_merge_opt_in', kwargs={'token': token})
		domain = Site.objects.get_current().domain
		if domain.startswith('http://') or domain.startswith('https://'):
			base = domain.rstrip('/')
		else:
			protocol = 'https' if getattr(settings, 'PROD_MODE', False) else 'http'
			base = f"{protocol}://{domain.strip('/')}"
		return f"{base}{path}"

	@classmethod
	def _extract_application(cls, user, edition: Edition) -> Optional[Application]:
		applications = (
			Application.objects.filter(user=user, edition=edition)
			.order_by('-submission_date')
		)
		return applications.first()

	@classmethod
	def _eligible_team_members(cls, team_code: str, edition: Edition) -> List[Application]:
		member_users = list(
			get_user_model().objects.filter(friendscode__code=team_code).distinct()
		)
		if not member_users:
			return []
		applications = (
			Application.objects.filter(user__in=member_users, edition=edition)
			.select_related('user')
		)
		app_map: Dict[int, Application] = {}
		for app in applications:
			app_map.setdefault(app.user_id, app)
		eligible = [app for app in app_map.values() if app.status == Application.STATUS_PENDING]
		if len(eligible) != len(member_users):
			return []
		return eligible

	@classmethod
	def _team_member_count(cls, team_code: str, edition: Edition) -> int:
		return len(cls._eligible_team_members(team_code, edition))

	@classmethod
	def process_opt_in_token(cls, token: str, actor=None) -> Dict[str, object]:
		try:
			payload = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
		except signing.BadSignature:
			return {'success': False, 'message': 'This link is invalid or has already been used.'}

		edition = cls.get_edition(payload.get('edition_id'))
		user_model = get_user_model()
		user = user_model.objects.filter(pk=payload.get('user_id')).first()
		if user is None:
			return {'success': False, 'message': 'User no longer exists in the system.'}

		with transaction.atomic():
			existing_code = cls._current_team_code(user)
			team_code = existing_code or payload.get('team_code') or ''
			if not team_code:
				friend = FriendsCode.objects.create(user=user)
				team_code = friend.code
			elif not existing_code:
				FriendsCode.objects.create(user=user, code=team_code)

			applications = cls._eligible_team_members(team_code, edition)
			member_count = len(applications)
			if member_count == 0:
				return {
					'success': False,
					'message': 'Your team is no longer eligible (no members with pending applications).',
				}
			if member_count > TARGET_TEAM_SIZE - 1:
				return {
					'success': False,
					'message': 'Only teams with three or fewer pending members can opt in for matching.',
				}

			existing_entry = FriendsMergePoolEntry.objects.filter(
				edition=edition,
				team_code=team_code,
			).first()
			if existing_entry and existing_entry.status == FriendsMergePoolEntry.STATUS_MATCHED:
				return {
					'success': False,
					'message': 'This team has already been matched.',
				}
			elif existing_entry and existing_entry.status == FriendsMergePoolEntry.STATUS_PENDING:
				FriendsMergeEventLog.objects.create(
					entry=existing_entry,
					event_type=FriendsMergeEventLog.EVENT_OPT_IN,
					actor=actor,
					metadata={'member_ids': [app.user_id for app in applications], 'duplicate': True},
				)
				return {
					'success': True,
					'message': 'Your team is already in the matching pool. We will be in touch soon.',
					'entry': existing_entry,
				}

			now = timezone.now()
			FriendsCode.objects.filter(code=team_code).update(
				seeking_merge=True,
				seeking_merge_updated_at=now,
			)

			entry, _ = FriendsMergePoolEntry.objects.update_or_create(
				edition=edition,
				team_code=team_code,
				defaults={
					'member_count': member_count,
					'status': FriendsMergePoolEntry.STATUS_PENDING,
					'matched_team_code': '',
					'matched_at': None,
					'trigger': FriendsMergePoolEntry.TRIGGER_AUTO,
				},
			)

			FriendsMergeEventLog.objects.create(
				entry=entry,
				actor=actor,
				event_type=FriendsMergeEventLog.EVENT_OPT_IN,
				metadata={'member_ids': [app.user_id for app in applications]},
			)
		return {
			'success': True,
			'message': 'Great! Your team has been added to the matching pool. We will email you once a match is found.',
			'entry': entry,
		}

	@classmethod
	def _build_member_contacts(cls, applications: Sequence[Application]) -> List[Dict[str, str]]:
		contacts = []
		for app in applications:
			data = app.form_data or {}
			contacts.append({
				'name': app.user.get_full_name() or app.user.get_username(),
				'email': app.user.email,
				'phone': cls._first_truthy(data, CONTACT_FIELD_CANDIDATES['phone']),
				'university': cls._first_truthy(data, CONTACT_FIELD_CANDIDATES['university']),
				'degree': cls._first_truthy(data, CONTACT_FIELD_CANDIDATES['degree']),
				'country': cls._first_truthy(data, CONTACT_FIELD_CANDIDATES['country']),
			})
		return contacts

	@staticmethod
	def _first_truthy(data: Dict[str, str], keys: Iterable[str]) -> str:
		for key in keys:
			value = data.get(key)
			if value:
				return value
		return ''

	@classmethod
	def gather_invite_targets(cls, edition: Edition, include_existing: bool = False) -> List[TeamInvite]:
		pending_apps = list(
			Application.objects.filter(edition=edition, status=Application.STATUS_PENDING)
			.select_related('user')
		)
		if not pending_apps:
			return []

		user_codes = {
			fc.user_id: fc.code
			for fc in FriendsCode.objects.filter(user__in=[app.user for app in pending_apps]).only('code', 'user_id')
		}

		entries: Dict[str, TeamInvite] = {}
		for app in pending_apps:
			code = user_codes.get(app.user_id)
			if code:
				entries.setdefault(code, TeamInvite(edition, '', 0, code, [])).members.append(app)
			else:
				key = f"solo-{app.user_id}"
				entries[key] = TeamInvite(edition, '', 1, None, [app])

		invites: List[TeamInvite] = []
		for key, invite in entries.items():
			if invite.team_code:
				if not include_existing and FriendsCode.objects.filter(code=invite.team_code, seeking_merge=True).exists():
					continue
				applications = cls._eligible_team_members(invite.team_code, edition)
				if not applications:
					continue
				if len(applications) > TARGET_TEAM_SIZE - 1:
					continue
				entry = FriendsMergePoolEntry.objects.filter(edition=edition, team_code=invite.team_code).first()
				if entry and entry.status in {FriendsMergePoolEntry.STATUS_PENDING, FriendsMergePoolEntry.STATUS_MATCHED} and not include_existing:
					continue
				invite.member_count = len(applications)
				invite.members = applications
			else:
				invite.member_count = 1
				invite.members = invite.members
			invite.token = cls.generate_opt_in_token(invite.members[0].user, edition, invite.team_code)
			invites.append(invite)
		return invites

	@staticmethod
	def _member_display_name(app: Application) -> str:
		user = app.user
		full_name = user.get_full_name().strip()
		if full_name:
			return full_name
		if user.first_name:
			return user.first_name
		username = getattr(user, 'username', '')
		if username:
			return username
		return (user.email or '').split('@')[0]

	@classmethod
	def _build_invite_context(
		cls,
		invite: TeamInvite,
		recipient_app: Optional[Application],
		accept_url: str,
		*,
		override_recipient_name: Optional[str] = None,
	) -> dict:
		primary_app = recipient_app or (invite.members[0] if invite.members else None)
		recipient_name = override_recipient_name
		if recipient_name is None and primary_app is not None:
			recipient_name = cls._member_display_name(primary_app)
		member_names = [cls._member_display_name(app) for app in invite.members]
		member_details = [
			{
				'name': cls._member_display_name(app),
				'email': getattr(app.user, 'email', ''),
			}
			for app in invite.members
		]
		context = {
			'edition': invite.edition,
			'accept_url': accept_url,
			'team_size': invite.member_count,
			'team_code': invite.team_code,
			'member_names': member_names,
			'member_details': member_details,
			'recipient_name': recipient_name or member_names[0] if member_names else '',
			'deadline': cls._format_deadline(),
			'team_label': invite.team_code or _('your profile'),
			'support_email': getattr(settings, 'HACKATHON_CONTACT_EMAIL', ''),
		}
		context.update(cls._email_defaults())
		return context

	@classmethod
	def _email_defaults(cls) -> dict:
		domain = getattr(settings, 'HOST', '') or Site.objects.get_current().domain
		protocol = 'https' if getattr(settings, 'PROD_MODE', False) else 'http'
		base_url = f"{protocol}://{domain}" if domain else ''
		logo_setting = getattr(settings, 'HACKATHON_EMAIL_LOGO', '')
		static_prefix = getattr(settings, 'STATIC_URL', '/static/')
		if logo_setting:
			if logo_setting.startswith('http'):
				logo_url = logo_setting
			elif base_url:
				logo_url = urljoin(base_url + '/', logo_setting.lstrip('/'))
			else:
				logo_url = logo_setting
		else:
			default_logo_path = f"{static_prefix.strip('/')}/img/logo-dark.png"
			logo_url = urljoin(base_url + '/', default_logo_path)
		return {
			'app_hack': getattr(settings, 'HACKATHON_NAME', ''),
			'app_contact': getattr(settings, 'HACKATHON_CONTACT_EMAIL', ''),
			'app_socials': getattr(settings, 'HACKATHON_SOCIALS', {}),
			'h_logo': logo_url,
		}
	@classmethod
	def build_invite_email(
		cls,
		invite: TeamInvite,
		recipient_app: Optional[Application] = None,
		*,
		override_email: Optional[str] = None,
		override_recipient_name: Optional[str] = None,
		request=None,
	):
		accept_url = cls.build_accept_url(invite.token)
		target_email = override_email or (recipient_app.user.email if recipient_app else None)
		if not target_email:
			return None
		context = cls._build_invite_context(
			invite,
			recipient_app,
			accept_url,
			override_recipient_name=override_recipient_name,
		)
		return Email('team_merge_invite', context, to=target_email, request=request)

	@classmethod
	def send_invite(
		cls,
		invite: TeamInvite,
		dry_run: bool = False,
		override_emails: Optional[Sequence[str]] = None,
	) -> None:
		recipients: List[tuple[Optional[Application], str]] = []
		member_lookup = {
			(getattr(app.user, 'email', '') or '').lower(): app
			for app in invite.members
		}
		if override_emails:
			for email in override_emails:
				if email:
					recipients.append((member_lookup.get(email.lower()), email))
		else:
			for app in invite.members:
				email = getattr(app.user, 'email', '')
				if email:
					recipients.append((app, email))
		if not recipients:
			return
		if dry_run:
			return
		for recipient_app, email in recipients:
			recipient_name = cls._member_display_name(recipient_app) if recipient_app else None
			if recipient_name is None and invite.members:
				recipient_name = cls._member_display_name(invite.members[0])
			email_obj = cls.build_invite_email(
				invite,
				recipient_app,
				override_email=email,
				override_recipient_name=recipient_name,
			)
			if email_obj is None:
				continue
			email_obj.send()

	@classmethod
	def run_matching(cls, edition: Optional[Edition | int] = None, allow_size_three: bool = False, trigger: str = FriendsMergePoolEntry.TRIGGER_AUTO) -> List[MatchGroupResult]:
		edition = cls.get_edition(edition)
		pending_entries = list(
			FriendsMergePoolEntry.objects.filter(edition=edition, status=FriendsMergePoolEntry.STATUS_PENDING)
			.order_by('created_at')
		)
		if not pending_entries:
			return []

		entry_map = {entry.team_code: entry for entry in pending_entries}
		member_counts = {
			team_code: cls._team_member_count(team_code, edition)
			for team_code in entry_map.keys()
		}
		# prune entries no longer eligible
		for team_code, count in list(member_counts.items()):
			if count == 0 or count > TARGET_TEAM_SIZE - 1:
				entry = entry_map[team_code]
				entry.status = FriendsMergePoolEntry.STATUS_REMOVED
				entry.save(update_fields=['status', 'updated_at'])
				FriendsMergeEventLog.objects.create(
					entry=entry,
					event_type=FriendsMergeEventLog.EVENT_REMOVED,
					message='Removed automatically due to ineligible member count.',
				)
				FriendsCode.objects.filter(code=team_code).update(seeking_merge=False)
				entry_map.pop(team_code)
				member_counts.pop(team_code)
		if not entry_map:
			return []

		groups, used_codes = cls._build_match_groups(entry_map, member_counts, target=TARGET_TEAM_SIZE)
		results: List[MatchGroupResult] = []
		# deadline handling for size 3
		if allow_size_three:
			remaining_entries = {code: entry_map[code] for code in entry_map if code not in used_codes}
			remaining_counts = {code: member_counts[code] for code in remaining_entries}
			deadline_groups, new_used = cls._build_match_groups(remaining_entries, remaining_counts, target=3)
			if deadline_groups:
				groups.extend(deadline_groups)
				used_codes.update(new_used)

		for group in groups:
			entries = [entry_map[code] for code in group]
			match_result = cls._merge_entries(entries, edition, trigger)
			if match_result:
				results.append(match_result)
		return results

	@classmethod
	def build_match_preview(
		cls,
		edition: Optional[Edition | int] = None,
		*,
		allow_size_three: bool = False,
		trigger: str = FriendsMergePoolEntry.TRIGGER_AUTO,
	) -> Optional[dict]:
		edition_obj = cls.get_edition(edition)
		pending_entries = list(
			FriendsMergePoolEntry.objects.filter(edition=edition_obj, status=FriendsMergePoolEntry.STATUS_PENDING)
			.order_by('created_at')
		)
		if not pending_entries:
			return None

		entry_map: Dict[str, FriendsMergePoolEntry] = {}
		member_counts: Dict[str, int] = {}
		for entry in pending_entries:
			count = cls._team_member_count(entry.team_code, edition_obj)
			if count == 0 or count > TARGET_TEAM_SIZE - 1:
				continue
			entry_map[entry.team_code] = entry
			member_counts[entry.team_code] = count

		if not entry_map:
			return None

		groups, used_codes = cls._build_match_groups(entry_map, member_counts, target=TARGET_TEAM_SIZE)
		if allow_size_three:
			remaining_entries = {code: entry_map[code] for code in entry_map if code not in used_codes}
			remaining_counts = {code: member_counts[code] for code in remaining_entries}
			deadline_groups, new_used = cls._build_match_groups(remaining_entries, remaining_counts, target=3)
			if deadline_groups:
				groups.extend(deadline_groups)
				used_codes.update(new_used)

		if not groups:
			return None

		sample_codes = groups[0]
		members_map: Dict[str, List[Application]] = {}
		for code in sample_codes:
			apps = cls._eligible_team_members(code, edition_obj)
			if not apps:
				return None
			members_map[code] = apps

		host_code = sample_codes[0]
		max_members = -1
		for code, applications in members_map.items():
			if len(applications) > max_members:
				host_code = code
				max_members = len(applications)

		all_apps: List[Application] = []
		member_groups: List[dict] = []
		for code in sample_codes:
			apps = members_map.get(code, [])
			all_apps.extend(apps)
			member_groups.append({
				'team_code': code,
				'members': cls._build_member_contacts(apps),
			})

		contacts = cls._build_member_contacts(all_apps)
		context = {
			'team_code': host_code,
			'members': contacts,
			'edition': edition_obj,
			'trigger': trigger,
		}
		email_obj = Email('team_merge_match', context, to='preview@example.com')
		return {
			'group_codes': sample_codes,
			'host_code': host_code,
			'member_groups': member_groups,
			'contact_count': len(contacts),
			'context': context,
			'subject': email_obj.subject.strip(),
			'html': email_obj.html_message,
		}

	@classmethod
	def _build_match_groups(
		cls,
		entry_map: Dict[str, FriendsMergePoolEntry],
		member_counts: Dict[str, int],
		target: int,
	) -> tuple[List[List[str]], Set[str]]:
		if target < 3:
			return [], set()
		size_buckets: Dict[int, List[str]] = {1: [], 2: [], 3: []}
		for team_code, count in member_counts.items():
			if count in size_buckets:
				size_buckets[count].append(team_code)
		for bucket in size_buckets.values():
			bucket.sort(key=lambda code: entry_map[code].created_at)

		groups: List[List[str]] = []
		used: Set[str] = set()

		if target == 4:
			while True:
				if size_buckets[3] and size_buckets[1]:
					group = [size_buckets[3].pop(0), size_buckets[1].pop(0)]
					groups.append(group)
					used.update(group)
					continue
				if len(size_buckets[2]) >= 2:
					group = [size_buckets[2].pop(0), size_buckets[2].pop(0)]
					groups.append(group)
					used.update(group)
					continue
				if size_buckets[2] and len(size_buckets[1]) >= 2:
					group = [size_buckets[2].pop(0), size_buckets[1].pop(0), size_buckets[1].pop(0)]
					groups.append(group)
					used.update(group)
					continue
				if len(size_buckets[1]) >= 4:
					group = [size_buckets[1].pop(0) for _ in range(4)]
					groups.append(group)
					used.update(group)
					continue
				break
		else:
			while True:
				if size_buckets[3]:
					code = size_buckets[3].pop(0)
					groups.append([code])
					used.add(code)
					continue
				if size_buckets[2] and size_buckets[1]:
					group = [size_buckets[2].pop(0), size_buckets[1].pop(0)]
					groups.append(group)
					used.update(group)
					continue
				if len(size_buckets[1]) >= 3:
					group = [size_buckets[1].pop(0) for _ in range(3)]
					groups.append(group)
					used.update(group)
					continue
				break
		return groups, used

	@classmethod
	def _merge_entries(cls, entries: Sequence[FriendsMergePoolEntry], edition: Edition, trigger: str) -> Optional[MatchGroupResult]:
		if not entries:
			return None
		team_codes = [entry.team_code for entry in entries]
		members_map: Dict[str, List[Application]] = {
			code: cls._eligible_team_members(code, edition)
			for code in team_codes
		}
		for code, apps in members_map.items():
			if not apps:
				entry = next(entry for entry in entries if entry.team_code == code)
				entry.status = FriendsMergePoolEntry.STATUS_REMOVED
				entry.save(update_fields=['status', 'updated_at'])
				FriendsMergeEventLog.objects.create(
					entry=entry,
					event_type=FriendsMergeEventLog.EVENT_REMOVED,
					message='Removed during matching because the team is no longer eligible.',
				)
				FriendsCode.objects.filter(code=code).update(seeking_merge=False)
				return None
		max_members = -1
		host_code = team_codes[0]
		for code, applications in members_map.items():
			if len(applications) > max_members:
				max_members = len(applications)
				host_code = code

		all_applications: Dict[int, Application] = {}
		for apps in members_map.values():
			for app in apps:
				all_applications[app.user_id] = app

		with transaction.atomic():
			for entry in entries:
				entry.member_count = len(members_map.get(entry.team_code, []))
				entry.status = FriendsMergePoolEntry.STATUS_MATCHED
				entry.matched_team_code = host_code
				entry.matched_at = timezone.now()
				entry.trigger = trigger
				entry.save(update_fields=['member_count', 'status', 'matched_team_code', 'matched_at', 'trigger', 'updated_at'])

			if host_code not in members_map:
				return None

			FriendsCode.objects.filter(code__in=[code for code in team_codes if code != host_code]).update(code=host_code)
			FriendsCode.objects.filter(code=host_code).update(seeking_merge=False, seeking_merge_updated_at=timezone.now())

			for entry in entries:
				FriendsMergeEventLog.objects.create(
					entry=entry,
					event_type=FriendsMergeEventLog.EVENT_MATCHED,
					metadata={'merged_codes': team_codes},
				)

			contacts = cls._build_member_contacts(all_applications.values())
			to_emails = [contact['email'] for contact in contacts if contact['email']]
			if to_emails:
				context = {
					'team_code': host_code,
					'members': contacts,
					'edition': edition,
					'trigger': trigger,
				}
				Email('team_merge_match', context, to_emails).send()
				for entry in entries:
					FriendsMergeEventLog.objects.create(
						entry=entry,
						event_type=FriendsMergeEventLog.EVENT_NOTIFICATION,
						metadata={'emails': to_emails},
					)

		return MatchGroupResult(team_code=host_code, member_ids=list(all_applications.keys()), trigger=trigger)

	@classmethod
	def _deadline_display(cls):
		deadline = DEFAULT_DEADLINE
		if deadline and is_naive(deadline):
			deadline = make_aware(deadline, timezone.utc)
		target_tz = get_fixed_timezone(-6 * 60)
		return deadline.astimezone(target_tz)

	@classmethod
	def _format_deadline(cls) -> str:
		deadline_local = cls._deadline_display()
		offset = deadline_local.utcoffset() or timedelta(0)
		offset_hours = int(offset.total_seconds() // 3600)
		tz_label = f"GMT{offset_hours:+d}"
		return f"{deadline_local.strftime('%B %d, %Y %H:%M')} {tz_label}"
