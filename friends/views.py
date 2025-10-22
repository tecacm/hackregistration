from django.conf import settings
from django.contrib import messages
from django.db import Error, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from django.views.generic import TemplateView
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin
from django.utils import timezone

from app.emails import EmailList
from application.mixins import ApplicationPermissionRequiredMixin
from application.models import Application, Edition, ApplicationTypeConfig, ApplicationLog
from application.views import ParticipantTabsMixin
from friends.filters import FriendsInviteTableFilter
from friends.forms import FriendsForm, TrackPreferenceForm
from friends.matchmaking import MatchmakingService
from friends.models import FriendsCode
from friends.tables import FriendInviteTable
from review.emails import get_invitation_or_waitlist_email
from review.views import ReviewApplicationTabsMixin, ApplicationListInvite
from user.mixins import LoginRequiredMixin, IsOrganizerMixin
from django.utils.translation import gettext_lazy as _


class JoinFriendsView(LoginRequiredMixin, ParticipantTabsMixin, TemplateView):
    template_name = "join_friends.html"

    def handle_permissions(self, request):
        permission = super().handle_permissions(request)
        edition = Edition.get_default_edition()
        if permission is None and not \
                Application.objects.filter(type__name="Hacker", user=request.user, edition=edition).exists():
            return self.handle_no_permission()
        return permission

    def get_current_tabs(self, **kwargs):
        return [("Applications", reverse("apply_home")), ("Friends", reverse("join_friends"))]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        edition_pk = Edition.get_default_edition()
        track_selection_open = True
        try:
            edition_obj = Edition.objects.only('track_selection_open').get(pk=edition_pk)
            track_selection_open = edition_obj.track_selection_open
        except Edition.DoesNotExist:
            track_selection_open = True
        try:
            friends_code = FriendsCode.objects.get(user=self.request.user)
            members = friends_code.get_members()
            context.update({
                "friends_code": friends_code,
                "members_count": members.count(),
            })
        except FriendsCode.DoesNotExist:
            context.update({
                "friends_form": FriendsForm(),
                "members_count": 0,
            })
        context.update({
            'friends_max_capacity': getattr(settings, 'FRIENDS_MAX_CAPACITY', None),
            'track_selection_open': track_selection_open,
        })
        return context

    def post(self, request, **kwargs):
        action = request.POST.get("action")
        if action not in ["create", "join", "leave"]:
            return HttpResponseBadRequest()
        method = getattr(self, action)
        return method()

    def create(self, **kwargs):
        default = {"user": self.request.user}
        code = kwargs.get("code", None)
        if code is not None:
            default["code"] = code
        FriendsCode(**default).save()
        return redirect(reverse("join_friends"))

    def join(self, **kwargs):
        form = FriendsForm(self.request.POST)
        if form.is_valid():
            code = form.cleaned_data.get("friends_code", None)
            friend_code = FriendsCode.objects.filter(code=code).first()
            if friend_code is None:
                form.add_error("friends_code", "Invalid code!")
            elif friend_code.reached_max_capacity():
                form.add_error("friends_code", "This team is already full")
            elif friend_code.is_closed():
                form.add_error("friends_code", "This team has one application invited and cannot be joined")
            else:
                return self.create(code=code)
        context = self.get_context_data()
        context.update({"friends_form": form})
        return self.render_to_response(context)

    def leave(self, **kwargs):
        try:
            friends_code = FriendsCode.objects.get(user=self.request.user)
            friends_code.delete()
        except FriendsCode.DoesNotExist:
            pass
        return redirect(reverse("join_friends"))


class FriendsListInvite(ApplicationPermissionRequiredMixin, IsOrganizerMixin, ReviewApplicationTabsMixin,
                        SingleTableMixin, FilterView):
    template_name = 'invite_friends.html'
    table_class = FriendInviteTable
    permission_required = 'application.can_invite_application'
    table_pagination = {'per_page': 50}
    filterset_class = FriendsInviteTableFilter

    def get_application_type(self):
        return self.request.GET.get('type', 'hacker')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application_type = get_object_or_404(ApplicationTypeConfig, name__iexact=self.get_application_type())
        context.update({'invite': True, 'application_type': application_type, 'Application': Application,
                        'application_stats': ApplicationListInvite.get_application_status(application_type)})
        return context

    def get_queryset(self):
        edition = Edition.get_default_edition()
        application_type = get_object_or_404(ApplicationTypeConfig, name__iexact=self.get_application_type())
        return self.table_class.get_queryset(application_type.application_set.filter(edition_id=edition,
                                                                                     user__friendscode__isnull=False))

    def post(self, request, *args, **kwargs):
        selection = request.POST.getlist('select')
        error = invited = 0
        emails = EmailList()
        for application in Application.objects.actual().filter(user__friendscode__code__in=selection,
                                                               status=Application.STATUS_PENDING):
            log = ApplicationLog(application=application, user=request.user, name='Invited by friends')
            log.changes = {'status': {'old': application.status, 'new': Application.STATUS_INVITED}}
            application.set_status(Application.STATUS_INVITED)
            try:
                with transaction.atomic():
                    application.save()
                    log.save()
                    invited += 1
                emails.add(get_invitation_or_waitlist_email(request, application))
            except Error:
                error += 1
        emails = emails.send_all()
        if error > 0:
            messages.error(request, _('Invited %s, Emails sent: %s, Error: %s') % (invited, emails or 0, error))
        else:
            messages.success(request, _('Invited: %s, Emails sent: %s' % (invited, emails or 0)))
        return redirect(reverse('invite_friends') + ('?type=%s' % self.request.GET.get('type', 'hacker')))


class FriendsTrackSelectionView(LoginRequiredMixin, ParticipantTabsMixin, TemplateView):
    template_name = 'friends_track_selection.html'

    def dispatch(self, request, *args, **kwargs):
        try:
            self.friends_code = FriendsCode.objects.get(user=request.user)
        except FriendsCode.DoesNotExist:
            messages.error(request, _('You need a team before selecting a track.'))
            return redirect('join_friends')
        self.edition_pk = Edition.get_default_edition()
        try:
            self.track_selection_open = Edition.objects.only('track_selection_open').get(pk=self.edition_pk).track_selection_open
        except Edition.DoesNotExist:
            self.track_selection_open = True
        return super().dispatch(request, *args, **kwargs)

    def get_current_tabs(self, **kwargs):
        return [('Applications', reverse('apply_home')), ('Friends', reverse('join_friends'))]

    def get_form(self):
        initial = {
            'track_pref_1': self.friends_code.track_pref_1 or '',
            'track_pref_2': self.friends_code.track_pref_2 or '',
            'track_pref_3': self.friends_code.track_pref_3 or '',
        }
        return TrackPreferenceForm(initial=initial)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        friends_code = self.friends_code
        assigned = bool(friends_code.track_assigned)
        assigned_label = friends_code.get_track_assigned_display() if assigned else ''
        eligible = friends_code.can_select_track()
        context.update({
            'group': friends_code,
            'assigned': assigned,
            'assigned_label': assigned_label,
            'track_selection_open': self.track_selection_open,
            'track_counts': FriendsCode.track_counts(),
            'eligible': eligible,
        })
        if not assigned and self.track_selection_open and eligible:
            context.setdefault('form', self.get_form())
        else:
            context['form'] = None
        return context

    def post(self, request, *args, **kwargs):
        if not self.track_selection_open:
            messages.error(request, _('Track selection is currently closed.'))
            return redirect('join_friends')
        if self.friends_code.track_assigned:
            messages.info(request, _('Your team already has an assigned track.'))
            return redirect('friends_track_selection')
        if not self.friends_code.can_select_track():
            messages.error(request, _('All teammates must be invited or confirmed before submitting preferences.'))
            return redirect('join_friends')

        form = TrackPreferenceForm(request.POST)
        if form.is_valid():
            preferences = (
                form.cleaned_data['track_pref_1'],
                form.cleaned_data['track_pref_2'],
                form.cleaned_data['track_pref_3'],
            )
            timestamp = timezone.now()
            FriendsCode.objects.filter(code=self.friends_code.code).update(
                track_pref_1=preferences[0],
                track_pref_2=preferences[1],
                track_pref_3=preferences[2],
                track_pref_submitted_at=timestamp,
            )
            messages.success(request, _('Track preferences saved. Organizers will assign tracks as capacities allow.'))
            return redirect('friends_track_selection')

        context = self.get_context_data(form=form)
        return self.render_to_response(context)


class FriendsMergeOptInView(TemplateView):
    template_name = 'friends/merge_opt_in.html'

    def get(self, request, *args, **kwargs):
        token = kwargs.get('token')
        result = MatchmakingService.process_opt_in_token(token)
        context = self.get_context_data(result=result)
        return self.render_to_response(context)
