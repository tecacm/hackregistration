import csv
import time

from django import forms
from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _
from django.db.models import Count, Q, F

from application import models
from app.emails import Email, EmailList
from friends.models import FriendsCode
from django.utils.text import slugify


class UniversityRosterForm(forms.Form):
    edition = forms.ModelChoiceField(
        queryset=models.Edition.objects.order_by('-order'),
        required=False,
        label=_('Edition'),
        help_text=_('Defaults to the current edition when left blank.'),
    )
    application_type = forms.ModelChoiceField(
        queryset=models.ApplicationTypeConfig.objects.order_by('name'),
        required=False,
        label=_('Application type'),
        help_text=_('Filter to a specific participant type.'),
    )
    school = forms.CharField(
        max_length=300,
        required=True,
        label=_('School / University'),
        help_text=_('Case-insensitive match; partial names are accepted.'),
    )
    statuses = forms.MultipleChoiceField(
        required=False,
        choices=models.Application.STATUS,
        label=_('Statuses'),
        widget=forms.CheckboxSelectMultiple,
        initial=[
            models.Application.STATUS_CONFIRMED,
            models.Application.STATUS_ATTENDED,
            models.Application.STATUS_INVITED,
            models.Application.STATUS_LAST_REMINDER,
        ],
        help_text=_('Restrict results to these statuses. Leave empty to include every status.'),
    )


class ApplicationAdmin(admin.ModelAdmin):
    change_list_template = 'admin/application/application/change_list.html'
    list_filter = ('type', 'edition')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')
    actions = ('email_team_segments',)

    class SegmentEmailForm(forms.Form):
        application_type = forms.CharField(initial='Hacker', label=_('Application type'))
        max_team_size = forms.IntegerField(min_value=1, initial=3, label=_('Max team size (<=)'))
        min_team_size = forms.IntegerField(min_value=1, initial=1, label=_('Min team size (>=)'))
        exact_team_size = forms.BooleanField(required=False, initial=False, label=_('Only exact team size'))
        include_no_team = forms.BooleanField(required=False, initial=True, label=_('Include no-team applicants'))
        only_full_missing_confirmed = forms.BooleanField(
            required=False,
            initial=False,
            label=_('Only teams full but missing confirmed'),
            help_text=_('Requires FRIENDS_MAX_CAPACITY; selects teams at capacity where not all members are Confirmed/Attended.')
        )
        include_discord = forms.BooleanField(
            required=False,
            initial=True,
            label=_('Include Discord invite'),
            help_text=_('Append the “Join our Discord” button and link to the email body.')
        )
        statuses = forms.MultipleChoiceField(
            required=True,
            label=_('Application statuses to include'),
            choices=[
                (models.Application.STATUS_PENDING, _('Under review')),
                (models.Application.STATUS_DUBIOUS, _('Dubious')),
                (models.Application.STATUS_NEEDS_CHANGE, _('Needs change')),
                (models.Application.STATUS_INVITED, _('Invited')),
                (models.Application.STATUS_LAST_REMINDER, _('Last reminder')),
                (models.Application.STATUS_CONFIRMED, _('Confirmed')),
                (models.Application.STATUS_ATTENDED, _('Attended')),
            ],
            initial=[
                models.Application.STATUS_PENDING,
                models.Application.STATUS_DUBIOUS,
                models.Application.STATUS_NEEDS_CHANGE,
            ],
            help_text=_('Pick the statuses to target (e.g., Invited, Confirmed).')
        )
        subject = forms.CharField(max_length=200, label=_('Email subject'))
        message = forms.CharField(widget=forms.Textarea(attrs={'rows': 8}), label=_('Email message'))
        dry_run = forms.BooleanField(required=False, initial=False, help_text=_('Preview only; do not send'))
        batch_size = forms.IntegerField(min_value=1, initial=100, label=_('Batch size'), help_text=_('Send in chunks to avoid timeouts (e.g., 50-200).'))
        batch_delay_ms = forms.IntegerField(min_value=0, initial=500, label=_('Delay between batches (ms)'), help_text=_('Throttle requests to respect ESP rate limits.'))

    def email_team_segments(self, request, queryset):
        """Admin action: compose and queue an email broadcast to hackers in small teams or with no team.

        Ignores the explicit selection; instead uses current default edition and chosen application type.
        """
        edition = models.Edition.get_default_edition()
        form = None
        context = dict(self.admin_site.each_context(request))
        # Preserve selected rows so Django admin recognizes this as a continued action
        selected_pks = list(queryset.values_list('pk', flat=True))
        index_val = request.POST.get('index', request.GET.get('index', '0'))
        initial = {
            'application_type': 'Hacker',
            'max_team_size': 3,
            'min_team_size': 1,
            'exact_team_size': False,
            'include_no_team': True,
            'only_full_missing_confirmed': False,
        }
        if request.method == 'POST' and (request.POST.get('preview') or request.POST.get('send')):
            form = self.SegmentEmailForm(request.POST)
            if form.is_valid():
                app_type = form.cleaned_data['application_type']
                max_size = form.cleaned_data['max_team_size']
                min_size = form.cleaned_data['min_team_size']
                exact_size = form.cleaned_data['exact_team_size']
                include_no_team = form.cleaned_data['include_no_team']
                only_full_missing_conf = form.cleaned_data['only_full_missing_confirmed']
                include_discord = form.cleaned_data['include_discord']
                subject = form.cleaned_data['subject']
                message = form.cleaned_data['message']
                # Not used for queue creation but kept for UI clarity
                _dry_run = form.cleaned_data['dry_run']

                # Allowed statuses come from the form selection
                allowed_statuses = form.cleaned_data['statuses']

                # Compute team code stats constrained to current edition
                codes_qs = FriendsCode.objects.filter(user__application__edition=edition)
                stats = codes_qs.values('code').annotate(
                    members=Count('user_id', distinct=True),
                    confirmed_members=Count(
                        'user_id',
                        filter=Q(
                            user__application__edition=edition,
                            user__application__status__in=[
                                models.Application.STATUS_CONFIRMED,
                                models.Application.STATUS_ATTENDED,
                            ]
                        ),
                        distinct=True,
                    ),
                )

                # Apply size constraints
                if exact_size:
                    stats = stats.filter(members=max_size)
                else:
                    stats = stats.filter(members__lte=max_size, members__gte=min_size)

                # Optionally restrict to teams at capacity but not fully confirmed
                friends_max_capacity = getattr(settings, 'FRIENDS_MAX_CAPACITY', None)
                if only_full_missing_conf and isinstance(friends_max_capacity, int):
                    stats = stats.filter(members__gte=friends_max_capacity).filter(confirmed_members__lt=F('members'))

                small_codes_list = list(stats.values_list('code', flat=True))

                # Applications of given type in current edition belonging to small teams
                small_team_apps = models.Application.objects.actual().filter(
                    edition=edition,
                    type__name__iexact=app_type,
                    status__in=allowed_statuses,
                    user__friendscode__code__in=small_codes_list
                )

                # Applications with no team at all
                no_team_apps = models.Application.objects.actual().filter(
                    edition=edition,
                    type__name__iexact=app_type,
                    status__in=allowed_statuses,
                ).filter(~Q(user__friendscode__code__isnull=False)) if include_no_team else models.Application.objects.none()

                apps_qs = (small_team_apps | no_team_apps).distinct()
                # Strict de-duplication to avoid any repeated recipients
                recipient_emails = list({e for e in apps_qs.values_list('user__email', flat=True).distinct() if e})
                recipient_emails.sort()

                # Build email preview using the same templates/context
                context.update({
                    'form': form,
                    'preview_count': len(recipient_emails),
                    'preview_emails': recipient_emails[:25],  # show a sample
                    'selected_pks': selected_pks,
                    'index_val': index_val,
                    'run_id': None,
                    'preview_subject': None,
                    'preview_html': None,
                    'include_discord': include_discord,
                })
                try:
                    preview_mail = Email(
                        'custom_broadcast',
                        {'subject': subject, 'message': message, 'include_discord': include_discord},
                        to='preview@example.com',
                        request=request,
                    )
                    context['preview_subject'] = preview_mail.subject
                    context['preview_html'] = preview_mail.html_message
                except Exception:
                    pass

                if request.POST.get('send'):
                    # Create a background broadcast job and enqueue recipients
                    run_id = f"segment:{request.user.id}:{int(time.time())}"
                    b = models.Broadcast.objects.create(
                        created_by=request.user,
                        run_id=run_id,
                        subject=subject,
                        message=message,
                        application_type=app_type,
                        max_team_size=max_size,
                        include_no_team=include_no_team,
                        include_discord=include_discord,
                        allowed_statuses=','.join(allowed_statuses),
                        edition_id=edition,
                        status=models.Broadcast.STATUS_PENDING,
                    )
                    # map email -> an application id (stable pick)
                    email_to_app = {}
                    for email, app_id in apps_qs.order_by('submission_date').values_list('user__email', 'pk'):
                        if email and email not in email_to_app:
                            email_to_app[email] = app_id
                    recipients = []
                    for email in recipient_emails:
                        app_id = email_to_app.get(email)
                        if not app_id:
                            continue
                        recipients.append(models.BroadcastRecipient(broadcast=b, application_id=app_id, email=email))
                    if recipients:
                        models.BroadcastRecipient.objects.bulk_create(recipients, batch_size=1000)
                    b.total = len(recipients)
                    b.save(update_fields=['total'])

                    # Kick off background processing in-process so the user doesn't need to run a command
                    try:
                        import threading
                        from application.broadcast_processor import process_one_broadcast
                        t = threading.Thread(
                            target=process_one_broadcast,
                            kwargs={
                                'broadcast_id': b.id,
                                'batch_size': 100,
                                'delay_ms': 500,
                                'max_retries': 2,
                            },
                            daemon=True,
                            name=f"broadcast-sender-{b.id}",
                        )
                        t.start()
                        self.message_user(request, _(f"Queued and started broadcast #{b.id} to {b.total} recipient(s)."))
                    except Exception:
                        # If thread start fails, we still have the queued broadcast; admin can run the processor manually
                        self.message_user(request, _(f"Queued broadcast #{b.id} to {b.total} recipient(s). Sender thread could not start; use the processor command."))
                    from django.shortcuts import redirect
                    from django.urls import reverse
                    return redirect(reverse('admin:application_broadcast_changelist'))

                # Just render preview
                return TemplateResponse(request, 'admin/application/email_team_segments.html', context)
        if form is None:
            form = self.SegmentEmailForm(initial=initial)
        context.update({'form': form, 'preview_count': None, 'preview_emails': [], 'selected_pks': selected_pks, 'index_val': index_val})
        return TemplateResponse(request, 'admin/application/email_team_segments.html', context)

    email_team_segments.short_description = _('Send email to small/no-team applicants…')

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'university-roster/',
                self.admin_site.admin_view(self.university_roster_view),
                name='application_application_university_roster',
            ),
        ]
        return custom + urls

    def university_roster_view(self, request):
        default_edition = None
        try:
            default_edition = models.Edition.objects.get(pk=models.Edition.get_default_edition())
        except models.Edition.DoesNotExist:
            default_edition = None

        initial = {}
        if default_edition:
            initial['edition'] = default_edition

        bound = request.GET.get('school') is not None or request.GET.get('download') == '1'
        if bound:
            form = UniversityRosterForm(request.GET, initial=initial)
        else:
            form = UniversityRosterForm(initial=initial)

        roster = []
        school_query = ''
        status_counts = {}
        total = 0
        if bound and form.is_valid():
            edition = form.cleaned_data['edition'] or default_edition
            app_type = form.cleaned_data['application_type']
            school_query = form.cleaned_data['school'].strip()
            statuses = form.cleaned_data['statuses']
            qs = models.Application.objects.all().select_related('user').order_by('user__first_name', 'user__last_name', 'user__email')
            if edition:
                qs = qs.filter(edition=edition)
            if app_type:
                qs = qs.filter(type=app_type)
            if statuses:
                qs = qs.filter(status__in=statuses)

            school_norm = school_query.lower()
            entries = []
            for app in qs:
                school_name = app.get_school_name()
                if not school_name:
                    continue
                if school_norm not in school_name.lower():
                    continue
                full_name = (app.get_full_name() or app.user.get_full_name() or '').strip()
                if not full_name:
                    full_name = app.user.email or _('Unknown')
                email = app.user.email or ''
                entries.append({
                    'name': full_name,
                    'email': email,
                    'status': app.get_status_display(),
                    'school': school_name,
                })

            entries.sort(key=lambda item: (item['name'].lower(), item['email']))
            roster = entries
            total = len(roster)
            if roster:
                from collections import Counter
                counts = Counter(entry['status'] for entry in roster)
                status_counts = sorted(counts.items(), key=lambda item: item[0])
            else:
                status_counts = []

            if request.GET.get('download') == '1' and roster:
                filename = f"university-roster-{slugify(school_query) or 'export'}.csv"
                response = HttpResponse(content_type='text/csv; charset=utf-8')
                response['Content-Disposition'] = f'attachment; filename={filename}'
                response.write('\ufeff')
                writer = csv.writer(response, lineterminator='\n')
                writer.writerow(['Full name', 'Email', 'Status', 'School'])
                for row in roster:
                    writer.writerow([row['name'], row['email'], row['status'], row['school']])
                return response

        context = dict(
            self.admin_site.each_context(request),
            title=_('University roster lookup'),
            form=form,
            roster=roster,
            school_query=school_query,
            status_breakdown=status_counts,
            total=total,
            filters_applied=bound and form.is_valid(),
        )
        return TemplateResponse(request, 'admin/application/university_roster.html', context)


class ApplicationTypeConfigAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from application.views import ApplicationApply
        if 'instance' in kwargs:
            self.initial['file_review_fields'] = kwargs['instance'].get_file_review_fields()
            ApplicationForm = ApplicationApply.get_form_class(kwargs['instance'].name)
            choices = []
            for name, field in ApplicationForm().declared_fields.items():
                if isinstance(field, forms.FileField):
                    choices.append((name, name))
            self.fields['file_review_fields'].widget = forms.CheckboxSelectMultiple(choices=choices)

    class Meta:
        model = models.ApplicationTypeConfig
        fields = '__all__'


class ApplicationTypeConfigAdmin(admin.ModelAdmin):
    form = ApplicationTypeConfigAdminForm
    exclude = ('name', )
    readonly_fields = ('share_link', )
    actions = ('regenerate_access_token', )

    def share_link(self, obj):
        """Readonly helper showing the dynamic apply URL when the type is hidden.

        Example: /application/apply/?type=Sponsor&token=<ACCESS_TOKEN>
        """
        if not obj.hidden:
            return '(visible type — no token required)'
        token = obj.access_token or str(obj.token)
        params = urlencode({'type': obj.name, 'token': token})
        return f"/application/apply/?{params}"

    share_link.short_description = 'Shareable apply link'

    def save_model(self, request, obj, form, change):
        """Ensure hidden types have an access token generated automatically if missing."""
        # If the type is hidden and no explicit access_token is provided, fallback to legacy token
        # or generate a new opaque token for convenience.
        if obj.hidden and not obj.access_token:
            # Prefer a short opaque token that fits in the configured max_length
            try:
                import secrets
                obj.access_token = secrets.token_urlsafe(32)[:64]
            except Exception:
                # As a very last resort keep it empty and rely on the legacy UUID token
                # (the view will accept obj.token when access_token is empty)
                pass
        super().save_model(request, obj, form, change)

    def regenerate_access_token(self, request, queryset):
        """Admin action to rotate the access_token for selected application types."""
        import secrets
        updated = 0
        for obj in queryset:
            obj.access_token = secrets.token_urlsafe(32)[:64]
            obj.save(update_fields=['access_token'])
            updated += 1
        self.message_user(request, f"Regenerated access token for {updated} type(s).")

    regenerate_access_token.short_description = 'Regenerate access token'

    def has_add_permission(self, request, obj=None):
        return False


class PromotionalCodeAdmin(admin.ModelAdmin):
    readonly_fields = ('uuid', )


admin.site.register(models.Application, ApplicationAdmin)
admin.site.register(models.ApplicationTypeConfig, ApplicationTypeConfigAdmin)
admin.site.register(models.ApplicationLog)
@admin.register(models.Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject', 'created_by', 'created_at', 'status', 'total', 'accepted')
    list_filter = ('status', 'created_at')
    search_fields = ('subject', 'run_id')
    readonly_fields = ('created_at', 'accepted')

@admin.register(models.BroadcastRecipient)
class BroadcastRecipientAdmin(admin.ModelAdmin):
    list_display = ('id', 'broadcast', 'email', 'status', 'attempts', 'updated_at')
    list_filter = ('status', 'updated_at')
    search_fields = ('email', 'broadcast__subject', 'broadcast__run_id')
    raw_id_fields = ('broadcast', 'application')

@admin.register(models.Edition)
class EditionAdmin(admin.ModelAdmin):
    list_display = ('name', 'order', 'track_selection_open')
    list_editable = ('track_selection_open', )
    ordering = ('-order', )
    search_fields = ('name', )

admin.site.register(models.PermissionSlip)
admin.site.register(models.PromotionalCode, PromotionalCodeAdmin)
