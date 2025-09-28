import django_filters as filters
from django import forms
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from app.mixins import BootstrapFormMixin
from application.models import Application


class ApplicationTableFilterForm(BootstrapFormMixin, forms.Form):
    bootstrap_field_info = {'': {
        'fields': [
            {'name': 'search', 'space': 8},
            {'name': 'under_age', 'space': 2},
            {'name': 'outside_mexico', 'space': 2},
            {'name': 'status', 'space': 12},
            {'name': 'type'}
        ]},
    }


class ApplicationTableFilterFormWithPromotion(ApplicationTableFilterForm):
    bootstrap_field_info = {'': {
        'fields': [
            {'name': 'search', 'space': 6},
            {'name': 'under_age', 'space': 2},
            {'name': 'outside_mexico', 'space': 2},
            {'name': 'promotional_code', 'space': 2},
            {'name': 'status', 'space': 12},
            {'name': 'type'}
        ]},
    }


class ApplicationTableFilter(filters.FilterSet):
    search = filters.CharFilter(method='search_filter', label=_('Search'))
    status = filters.MultipleChoiceFilter(choices=Application.STATUS,
                                          widget=forms.CheckboxSelectMultiple(attrs={'class': 'inline'}))
    type = filters.CharFilter(field_name='type__name', widget=forms.HiddenInput)
    under_age = filters.BooleanFilter(method='under_age_filter', label=_('Under age'))
    outside_mexico = filters.BooleanFilter(method='outside_mexico_filter', label=_('Outside Mexico'))

    def under_age_filter(self, queryset, name, value):
        eighteen_years_ago = timezone.now().date() - timezone.timedelta(days=18*365.25)
        if value:
            return queryset.filter(user__birth_date__gt=eighteen_years_ago)
        return queryset.filter(user__birth_date__lte=eighteen_years_ago)

    def search_filter(self, queryset, name, value):
        return queryset.filter(Q(user__email__icontains=value) | Q(user__first_name__icontains=value) |
                               Q(user__last_name__icontains=value))

    def outside_mexico_filter(self, queryset, name, value):
        # When checked, exclude applications whose JSON data has country == "Mexico" (or "México").
        if not value:
            return queryset
        return queryset.exclude(
            Q(data__icontains='"country": "Mexico"') |
            Q(data__icontains='"country":"Mexico"') |
            Q(data__icontains='"country": "México"') |
            Q(data__icontains='"country":"México"')
        )

    class Meta:
        model = Application
        fields = ['search', 'status', 'type']
        form = ApplicationTableFilterForm


class ApplicationTableFilterWithPromotion(ApplicationTableFilter):
    class Meta(ApplicationTableFilter.Meta):
        fields = ['search', 'status', 'type', 'promotional_code']
        form = ApplicationTableFilterFormWithPromotion
