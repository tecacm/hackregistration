from django.contrib import admin
from django.conf import settings
from django.utils.html import format_html
from django.db.models import Count
from django.db import connection
from django.http import HttpResponse
import csv

from friends.models import FriendsCode
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
		'code', 'members_count', 'capacity', 'pending_count', 'invited_count', 'confirmed_count', 'devpost_link',
	)
	search_fields = ('code', 'user__email', 'user__first_name', 'user__last_name')
	readonly_fields = ('code', 'members_count', 'capacity', 'devpost_link', 'members_list',
	                  'pending_count', 'invited_count', 'confirmed_count')
	fields = (
		'code', 'devpost_url', 'devpost_link',
		'members_count', 'capacity',
		'members_list',
	)
	list_filter = (MembersSizeFilter, HasDevpostFilter, AnyInvitedConfirmedFilter)
	actions = ('export_csv', 'open_invite_view')

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
		# Show the code once per group: ensure we list unique codes with arbitrary representative record.
		return super().get_list_display(request)

	def get_search_results(self, request, queryset, search_term):
		qs, use_distinct = super().get_search_results(request, queryset, search_term)
		return qs, use_distinct

	def save_model(self, request, obj, form, change):
		# Save and propagate Devpost URL to all entries with same code
		super().save_model(request, obj, form, change)
		FriendsCode.objects.filter(code=obj.code).update(devpost_url=obj.devpost_url)
