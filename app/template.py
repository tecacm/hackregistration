from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from app.utils import get_theme, is_installed
from application.models import ApplicationTypeConfig


def add_file_nav(nav, request):
    application_types = ApplicationTypeConfig.get_type_files()
    default_type_file = 'Hacker'
    if default_type_file in application_types:
        application_types.remove(default_type_file)
        application_types.insert(0, default_type_file)
    if len(application_types) > 0:
        all_perm = request.user.has_perm('application.can_review_files')
        for application_type in application_types:
            if all_perm or request.user.has_perm('application.can_review_files_%s' % application_type.lower()):
                nav.extend([('Files', reverse('file_review') + '?type=%s' % default_type_file), ])
                return nav
    return nav


def get_main_nav(request):
    nav = []
    # Some code paths that render error pages pass a bare WSGIRequest
    # which may not have `user` attached (AuthenticationMiddleware not run).
    # Guard all access to `request.user` here so templates can render
    # friendly error pages instead of raising AttributeError.
    if not hasattr(request, 'user') or not getattr(request.user, 'is_authenticated', False):
        if getattr(settings, 'HACKATHON_LANDING', None) is not None:
            nav.append(('Landing page', getattr(settings, 'HACKATHON_LANDING')))
        return nav
    try:
        if request.user.is_staff:
            nav.append(('Admin', reverse('admin:index')))
        if request.user.is_organizer():
            nav.extend([('Review', reverse('application_review'))])
            nav = add_file_nav(nav, request)
        else:
            if getattr(settings, 'HACKATHON_LANDING', None) is not None:
                nav.append(('Landing page', getattr(settings, 'HACKATHON_LANDING')))
    except Exception:
        # Defensive: if there's any failure querying user groups/permissions
        # while building navigation (DB problems, recursion, etc.), fall
        # back to a minimal nav so templates can continue rendering.
        if getattr(settings, 'HACKATHON_LANDING', None) is not None:
            nav.append(('Landing page', getattr(settings, 'HACKATHON_LANDING')))
    if hasattr(request, 'user') and request.user.has_module_perms('event'):
        nav.append(('Checkin', reverse('checkin_list')))
        if is_installed('event.messages') and request.user.has_perm('event_messages.view_announcement'):
            nav.append(('Announcements', reverse('announcement_list')))
        if is_installed('event.meals') and request.user.has_perm('meals.can_checkin_meals'):
            nav.append(('Meals', reverse('meals_list')))
    if hasattr(request, 'user') and request.user.is_organizer():
        if request.user.has_module_perms('tables'):
            nav.extend([('Tables', reverse('tables_home'))])
        if request.user.has_module_perms('stats'):
            nav.extend([('Stats', reverse('stats_home'))])
    return nav


def get_date(text):
    try:
        return timezone.datetime.strptime(text, '%d/%m/%Y')
    except ValueError:
        return None


def app_variables(request):
    try:
        # Compute whether to show re-entry disclaimer only in the week before the event
        hack_start_dt = get_date(getattr(settings, 'HACKATHON_START_DATE', ''))
        now_date = timezone.localdate()
        show_reentry_disclaimer = False
        show_devpost_until_start = True
        start_date = None
        if hack_start_dt is not None:
            try:
                start_date = hack_start_dt.date()
            except AttributeError:
                # If get_date returns a date already
                start_date = hack_start_dt
            days_until = (start_date - now_date).days
            show_reentry_disclaimer = 0 <= days_until <= 7
            # Devpost visible starting on the start date (hidden before the event day)
            show_devpost_until_start = now_date >= start_date

        return {
            'main_nav': get_main_nav(request),
            'app_hack': getattr(settings, 'HACKATHON_NAME'),
            'app_description': getattr(settings, 'HACKATHON_DESCRIPTION'),
            'app_author': getattr(settings, 'HACKATHON_ORG'),
            'app_name': getattr(settings, 'APP_NAME'),
            'app_socials': getattr(settings, 'HACKATHON_SOCIALS', []),
            'app_contact': getattr(settings, 'HACKATHON_CONTACT_EMAIL', ''),
            'app_theme': getattr(settings, 'THEME') == 'both',
            'app_landing': getattr(settings, 'HACKATHON_LANDING'),
            'theme': get_theme(request),
            'captcha_site_key': getattr(settings, 'GOOGLE_RECAPTCHA_SITE_KEY', ''),
            'socialaccount_providers': getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {}),
            'auth_password_validators': getattr(settings, 'PASSWORD_VALIDATORS', {}),
            'tables_export_supported': getattr(settings, 'DJANGO_TABLES2_EXPORT_FORMATS', []),
            'participant_can_upload_permission_slip': getattr(settings, 'PARTICIPANT_CAN_UPLOAD_PERMISSION_SLIP', False),
            'hack_start_date': get_date(getattr(settings, 'HACKATHON_START_DATE', '')),
            'hack_end_date': get_date(getattr(settings, 'HACKATHON_END_DATE', '')),
            'hack_location': getattr(settings, 'HACKATHON_LOCATION', ''),
            'show_reentry_disclaimer': show_reentry_disclaimer,
            'show_devpost_until_start': show_devpost_until_start,
        }
    except Exception:
        # If any failure occurs while computing variables (including recursion
        # or DB problems), return a minimal safe context so templates can still
        # render a page instead of raising a 500.
        try:
            return {
                'main_nav': [],
                'app_hack': getattr(settings, 'HACKATHON_NAME', ''),
                'app_name': getattr(settings, 'APP_NAME', ''),
                'theme': 'light',
            }
        except Exception:
            return {}
