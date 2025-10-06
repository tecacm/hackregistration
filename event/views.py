import string
from random import choice

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin
from django.utils.translation import gettext_lazy as _

from application.mixins import AnyApplicationPermissionRequiredMixin
from application.models import Application, ApplicationLog, Edition
from django.conf import settings
from event.filters import CheckinTableFilter
from event.tables import CheckinTable


class CheckinList(AnyApplicationPermissionRequiredMixin, SingleTableMixin, FilterView):
    permission_required = 'event.can_checkin'
    template_name = 'checkin_list.html'
    table_class = CheckinTable
    filterset_class = CheckinTableFilter

    def get_queryset(self):
        return get_user_model().objects.filter(Q(application__status=Application.STATUS_CONFIRMED,
                                                 application__edition=Edition.get_default_edition()) |
                                               Q(groups__name='Organizer', qr_code='')).distinct()


class CheckinUser(TemplateView):
    template_name = 'checkin_user.html'

    def has_permission(self, types):
        permission = 'event.can_checkin'
        if self.request.user.has_perm(permission):
            return True
        for application_type in types:
            if not self.request.user.has_perm('%s_%s' % (permission, application_type.lower())):
                return False
        return True

    def get_accepted_status_to_checkin(self):
        accepted_status = [Application.STATUS_CONFIRMED]
        if self.request.user.is_staff:
            accepted_status.append(Application.STATUS_ATTENDED)
        return accepted_status

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        User = get_user_model()
        try:
            uid = User.decode_encoded_pk(kwargs.get('uid'))
            user = User.objects.get(pk=uid)
            accepted_status = self.get_accepted_status_to_checkin()
            application_types = list(user.application_set.actual().filter(status__in=accepted_status)
                                     .values_list('type__name', flat=True))
            if user.is_organizer():
                application_types.append('Organizer')
            context.update({'app_user': user, 'types': application_types,
                            'has_permission': self.has_permission(types=application_types)})
        except (User.DoesNotExist, ValueError):
            pass
        return context

    def get_code(self):
        qr_code = self.request.POST.get('qr_code', None)
        if qr_code == '':
            return ''.join([choice(string.ascii_letters + string.digits + string.punctuation) for i in range(12)])
        return qr_code

    def manage_application_confirm(self, application):
        application.set_status(Application.STATUS_ATTENDED)
        application.save()
        application_log = ApplicationLog(application=application, user=self.request.user, comment='',
                                         name='Checked-in')
        application_log.changes = {'status': {'new': Application.STATUS_ATTENDED,
                                              'old': Application.STATUS_CONFIRMED}}
        application_log.save()

    def manage_application_attended(self, application):
        application_log = ApplicationLog(application=application, user=self.request.user, comment='',
                                         name='Changed QR code')
        application_log.save()

    def redirect_successful(self):
        next_ = self.request.GET.get('next', reverse('event:checkin_list'))
        if next_[0] != '/':
            next_ = reverse('event:checkin_list')
        return redirect(next_)

    def post(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        qr_code = self.get_code()
        if context['has_permission'] and len(context['types']) > 0 and qr_code is not None:
            user = context['app_user']
            user.qr_code = qr_code
            accepted_status = self.get_accepted_status_to_checkin()
            applications = user.application_set.actual().filter(status__in=accepted_status)\
                .select_related('type')
            groups = Group.objects.filter(name__in=context['types'])
            with transaction.atomic():
                user.save()
                user.groups.add(*groups)
                for application in applications:
                    if application.status == Application.STATUS_CONFIRMED:
                        self.manage_application_confirm(application)
                    else:
                        self.manage_application_attended(application)
            messages.success(request, _('User checked in!'))
            return self.redirect_successful()
        messages.error(request, _('Permission denied'))
        return self.render_to_response(context)


class CheckinAdminList(CheckinList):
    def get_queryset(self):
        if self.request.user.is_staff:
            return get_user_model().objects.filter(Q(application__status__in=[Application.STATUS_CONFIRMED,
                                                                              Application.STATUS_ATTENDED],
                                                     application__edition=Edition.get_default_edition()) |
                                                   Q(groups__name='Organizer')).distinct()
        return get_user_model().objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'admin': True})
        return context


class JudgesGuideView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'judges/guide.html'
    login_url = 'account_login'

    def test_func(self):
        user = self.request.user
        if not getattr(user, 'is_authenticated', False):
            return False
        if user.is_superuser:
            return True
        try:
            return user.groups.filter(name__in=['Judge', 'Organizer']).exists()
        except Exception:
            return False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'overview': {
                'tagline': _('Expo Judges Training'),
                'mission': _('Expo Judging Hub'),
                'about': [
                    _('HackMTY is the largest student hackathon in Latin America.'),
                    _('We aim to learn, collaborate, build, and have fun while solving real-world challenges.'),
                    _('Teams generate, develop, and ship products or services in under 36 hours.'),
                ],
            },
            'role': {
                'headline': _('What does an expo judge do?'),
                'responsibilities': [
                    _('Evaluate 8–10 teams that submitted their project to the official platform.'),
                    _('Score every team consistently using the official rubric.'),
                    _('Select the top 10 finalists that advance to the final panel.'),
                ],
                'criteria': [_('Innovation'), _('Technical Challenge'), _('User Experience'), _('Impact'), _('Presentation')],
            },
            'reminders': {
                'title': _('Key reminders'),
                'notes': [
                    _('Hardware and software projects require different expertise—assess each team within its context.'),
                    _('Capture quick notes on anything unclear so you can follow up with mentors or other judges.'),
                    _('Skip questions about school or hometown; keep the conversation focused on the project.'),
                    _('If you know someone on the team, let staff know so we can reassign you.'),
                    _('Balance technical depth and polish—both take time and should influence the score.'),
                ],
                'interaction_tips': [
                    _('Ask open questions: What did you learn? Which technologies did you use? What was the hardest challenge and how did you solve it?'),
                    _('Dig into how the team divided the work, managed time, and leveraged pre-built components.'),
                    _('If something is unclear, ask for a short demo or clarification and take notes.'),
                    _('Celebrate the team’s effort—everyone has poured 36+ hours into their solution.'),
                ],
            },
            'red_flags': [
                _('Improper use of licenses, copyrights, or third-party assets.'),
                _('Obscene, disrespectful, or code-of-conduct-breaking content.'),
                _('A level of polish that seems impossible in 36 hours without clear justification—ask probing questions.'),
            ],
            'donts': [
                _('Do not assign a score if you do not understand the project—ask for support instead.'),
                _('Do not evaluate teams where you have a conflict of interest.'),
                _('Do not discriminate based on background, gender, school, or any personal attribute.'),
            ],
            'score_scale': [
                {'score': 6, 'label': _('Outstanding')},
                {'score': 5, 'label': _('Excellent')},
                {'score': 4, 'label': _('Very good')},
                {'score': 3, 'label': _('Good')},
                {'score': 2, 'label': _('Fair')},
                {'score': 1, 'label': _('Needs improvement')},
            ],
            'rubrics': [
                {
                    'category': _('Innovation'),
                    'criteria': [
                        _('Originality of the solution.'),
                        _('Intersection of multiple disciplines or uncommon technologies.'),
                    ],
                },
                {
                    'category': _('Technical Challenge'),
                    'criteria': [
                        _('Integration quality of the chosen technologies.'),
                        _('Overall technical complexity tackled by the team.'),
                        _('Functional progress of the prototype during the hackathon.'),
                    ],
                },
                {
                    'category': _('User Experience'),
                    'criteria': [
                        _('Visual design and ease of use.'),
                        _('Clarity of the target user, journey, or market case.'),
                    ],
                },
                {
                    'category': _('Impact'),
                    'criteria': [
                        _('Inclusive, social, or positive impact potential.'),
                        _('Sustainable business or monetization strategy.'),
                    ],
                },
                {
                    'category': _('Presentation'),
                    'criteria': [
                        _('Storytelling, branding, and narrative flow.'),
                        _('Team collaboration and multidisciplinary balance.'),
                    ],
                },
            ],
            'schedule': {
                'title': _('Judging schedule'),
                'blocks': [
                    {'label': _('Team pitch'), 'duration': _('3 minutes')},
                    {'label': _('Judge questions and scoring'), 'duration': _('2 minutes')},
                ],
                'reminders': [
                    _('Give every team the same amount of time and stay on schedule.'),
                    _('Only one judging group per team at a time—avoid crowding projects.'),
                    _('Staff members are nearby to help with timing, logistics, or any issue.'),
                ],
            },
            'judging_portal_url': getattr(settings, 'JUDGING_PORTAL_URL', '#'),
        })
        return context
