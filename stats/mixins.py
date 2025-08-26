from app.mixins import PermissionRequiredMixin
from django.contrib.auth.models import Group


class StatsPermissionRequiredMixin(PermissionRequiredMixin):
    def has_permission(self, application_type=None):
        user = self.request.user
        is_org = getattr(user, 'is_organizer', None)
        is_org = is_org() if callable(is_org) else bool(is_org)
        is_sponsor = user.groups.filter(name='Sponsor').exists()
        if not (is_org or is_sponsor):
            return False
        perms = self.get_permission_required()
        model_name = self.kwargs.get('model', '').lower()
        model_perms = ['%s_%s' % (perm, model_name) for perm in perms]
        # Organizers: use existing perms; Sponsors: allow access by default.
        if is_sponsor:
            return True
        return user.has_perms(perms) or user.has_perms(model_perms)
