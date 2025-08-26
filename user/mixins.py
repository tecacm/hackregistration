from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.shortcuts import redirect
from django.utils.translation import gettext as _


class CustomAccessMixin(AccessMixin):
    def handle_permissions(self, request):
        return None

    def dispatch(self, request, *args, **kwargs):
        return self.handle_permissions(request) or super().dispatch(request, *args, **kwargs)


class EmailNotVerifiedMixin(CustomAccessMixin):
    def handle_permissions(self, request):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.email_verified:
            messages.warning(request, _("Your email has already been verified"))
            return redirect('home')
        return super().handle_permissions(request)


class LoginRequiredMixin(CustomAccessMixin):
    def handle_permissions(self, request):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.email_verified:
            return redirect('needs_verification')
        return super().handle_permissions(request)


class IsOrganizerMixin(LoginRequiredMixin):
    def handle_permissions(self, request):
        response = super().handle_permissions(request)
        # IMPORTANT: call the method is_organizer() (previously missing parentheses made this always truthy)
        if response is None and not request.user.is_organizer():
            return self.handle_no_permission()
        return response


class IsSponsorOrOrganizerMixin(LoginRequiredMixin):
    def handle_permissions(self, request):
        response = super().handle_permissions(request)
        if response is None and not (request.user.is_organizer() or getattr(request.user, 'is_sponsor', lambda: False)()):
            return self.handle_no_permission()
        return response


class IsOrganizerOrSponsorMixin(LoginRequiredMixin):
    def handle_permissions(self, request):
        response = super().handle_permissions(request)
        if response is not None:
            return response
        user = request.user
        is_org = user.is_organizer()
        is_sponsor = user.groups.filter(name='Sponsor').exists()
        if not (is_org or is_sponsor):
            return self.handle_no_permission()
        return None
