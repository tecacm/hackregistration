from django.forms import forms
import django_filters as filters

from app.mixins import BootstrapFormMixin
from application.models import Application
from django.utils.translation import gettext_lazy as _


class FriendsInviteTableFilterForm(BootstrapFormMixin, forms.Form):
    bootstrap_field_info = {'': {
        'fields': [
            {'name': 'half_accepted', 'space': 3},
            {'name': 'are_pending', 'space': 3},
            {'name': 'has_outside_city', 'space': 3},
        ]},
    }


class FriendsInviteTableFilter(filters.FilterSet):
    YES = 'yes'
    NO = 'no'
    CHOICES = ((YES, _('Yes')),
               (NO, _('No')))

    half_accepted = filters.ChoiceFilter(method='half_accepted_filter', choices=CHOICES,
                                         label=_('Are half members accepted?'))
    are_pending = filters.ChoiceFilter(method='pending_filter', choices=CHOICES,
                                       label=_('Is there any member on pending?'))
    has_outside_city = filters.ChoiceFilter(method='outside_city_filter', choices=CHOICES,
                                            label=_('At least one member outside host city'))

    def pending_filter(self, queryset, name, value):
        result = []
        operation = {self.YES: lambda x: x > 0, self.NO: lambda x: x <= 0}[value]
        for instance in queryset:
            if operation(instance['pending']):
                result.append(instance['code'])
        return queryset.filter(user__friendscode__code__in=result)

    def half_accepted_filter(self, queryset, name, value):
        result = []
        operation = {self.YES: lambda x, y: x <= y, self.NO: lambda x, y: x > y}[value]
        for instance in queryset:
            if operation((instance['members'] // 2), instance['accepted']):
                result.append(instance['code'])
        return queryset.filter(user__friendscode__code__in=result)

    def outside_city_filter(self, queryset, name, value):
        from django.conf import settings
        from application.models import Application
        import json
        host_city = (getattr(settings, 'HACKATHON_LOCATION', 'Monterrey') or 'Monterrey').strip().lower()
        # Collect codes with at least one origin city different from host
        codes_with_diff = set()
        # Iterate through relevant applications (those tied to a friends code in current queryset)
        codes_in_queryset = set(queryset.values_list('user__friendscode__code', flat=True))
        apps = Application.objects.filter(user__friendscode__code__in=codes_in_queryset)
        for app in apps.only('data', 'user__friendscode__code'):
            try:
                data = json.loads(app.data or '{}')
            except json.JSONDecodeError:
                continue
            origin = str(data.get('origin', '')).strip().lower()
            if origin and origin != host_city:
                code = getattr(app.user.friendscode_set.order_by('-id').first(), 'code', None)
                if code:
                    codes_with_diff.add(code)
        if value == self.YES:
            return queryset.filter(user__friendscode__code__in=codes_with_diff)
        else:
            return queryset.exclude(user__friendscode__code__in=codes_with_diff)

    class Meta:
        model = Application
        fields = ['half_accepted', 'are_pending', 'has_outside_city']
        form = FriendsInviteTableFilterForm
