from django.conf import settings
from django.contrib import messages
from django.db import Error, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from django.views.generic import TemplateView
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin

from app.emails import EmailList
from application.mixins import ApplicationPermissionRequiredMixin
from application.models import Application, Edition, ApplicationTypeConfig, ApplicationLog
from application.views import ParticipantTabsMixin
from friends.filters import FriendsInviteTableFilter
from friends.forms import FriendsForm, DevpostForm
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
        if (
            permission is None
            and not Application.objects.actual()
                .exclude(status=Application.STATUS_CANCELLED)
                .filter(type__name="Hacker", user=request.user, edition=edition)
                .exists()
        ):
            return self.handle_no_permission()
        return permission

    def get_current_tabs(self, **kwargs):
        return [("Applications", reverse("apply_home")), ("Friends", reverse("join_friends"))]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        friends_code = FriendsCode.objects.filter(user=self.request.user).order_by('-id').first()
        if friends_code:
            context.update({"friends_code": friends_code})
            members_count = friends_code.get_members().count()
            context.update({"members_count": members_count})
            # If team is full, show Devpost URL entry
            friends_max_capacity = getattr(settings, 'FRIENDS_MAX_CAPACITY', None)
            if friends_max_capacity and members_count >= friends_max_capacity:
                context.update({"devpost_form": DevpostForm(initial={'devpost_url': friends_code.devpost_url})})
        else:
            context.update({"friends_form": FriendsForm()})
        context.update({'friends_max_capacity': getattr(settings, 'FRIENDS_MAX_CAPACITY', None)})
        return context

    def post(self, request, **kwargs):
        action = request.POST.get("action")
        if action not in ["create", "join", "leave", "set_devpost"]:
            return HttpResponseBadRequest()
        method = getattr(self, action)
        return method()

    def create(self, **kwargs):
        default = {"user": self.request.user}
        code = kwargs.get("code", None)
        if code is not None:
            default["code"] = code
        # Ensure the user holds only one FriendsCode record
        FriendsCode.objects.filter(user=self.request.user).delete()
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
            elif friend_code.is_closed_for_user(self.request.user):
                # Allow switching teams even if the target team is closed,
                # as long as the joining user is already invited/confirmed/attended in this edition
                edition_pk = Edition.get_default_edition()
                user_app = Application.objects.filter(user=self.request.user, edition_id=edition_pk).first()
                if not user_app or user_app.status not in FriendsCode.STATUS_NOT_ALLOWED_TO_JOIN_TEAM:
                    form.add_error("friends_code", "This team has one application invited and cannot be joined")
                else:
                    return self.create(code=code)
            else:
                return self.create(code=code)
        context = self.get_context_data()
        context.update({"friends_form": form})
        return self.render_to_response(context)

    def leave(self, **kwargs):
        FriendsCode.objects.filter(user=self.request.user).delete()
        return redirect(reverse("join_friends"))

    def set_devpost(self, **kwargs):
        friends_code = FriendsCode.objects.filter(user=self.request.user).order_by('-id').first()
        if not friends_code:
            return redirect(reverse("join_friends"))
        members_count = friends_code.get_members().count()
        friends_max_capacity = getattr(settings, 'FRIENDS_MAX_CAPACITY', None)
        if not (friends_max_capacity and members_count >= friends_max_capacity):
            messages.error(self.request, _('Your team must be full to set the Devpost URL.'))
            return redirect(reverse("join_friends"))
        form = DevpostForm(self.request.POST)
        if form.is_valid():
            url = form.cleaned_data['devpost_url']
            # Propagate to all records of the same group code
            FriendsCode.objects.filter(code=friends_code.code).update(devpost_url=url)
            messages.success(self.request, _('Devpost URL saved.'))
        else:
            context = self.get_context_data()
            context.update({"devpost_form": form})
            return self.render_to_response(context)
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
        qs = application_type.application_set.filter(edition_id=edition, user__friendscode__isnull=False)
        code = self.request.GET.get('code')
        if code:
            qs = qs.filter(user__friendscode__code=code)
        return self.table_class.get_queryset(qs)

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
