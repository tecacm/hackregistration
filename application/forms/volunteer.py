from django import forms
from django.conf import settings
from django.templatetags.static import static
from django.utils.functional import lazy
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from user.choices import LEVELS_OF_STUDY

from application.forms.base import ApplicationForm, PREVIOUS_HACKS, HACK_DAYS, ENGLISH_LEVELS

static_lazy = lazy(static, str)


class VolunteerForm(ApplicationForm):
    bootstrap_field_info = {
        '': {
            'fields': [
          {'name': 'university', 'space': 6}, {'name': 'degree', 'space': 6},
                {'name': 'country', 'space': 6}, {'name': 'origin', 'space': 6}]},
        _('Hackathons'): {
            'fields': [{'name': 'night_shifts', 'space': 4}, {'name': 'first_time_volunteering', 'space': 4},
                       {'name': 'which_hack', 'space': 4, 'visible': {'first_time_volunteering': True}},
                       {'name': 'attendance', 'space': 4}, {'name': 'english_level', 'space': 4},
                       {'name': 'lennyface', 'space': 4}, {'name': 'friends', 'space': 6},
                       {'name': 'more_information', 'space': 6}, {'name': 'description', 'space': 6},
              {'name': 'discover_hack', 'space': 6}, {'name': 'level_of_study', 'space': 12}],
            'description': _('Tell us a bit about your experience and preferences in this type of event.')},

    }

    university = forms.CharField(max_length=300, label=_('What university do you study at?'),
                                 help_text=_('Current or most recent school you attended.'))

    degree = forms.CharField(max_length=300, label=_('What\'s your major/degree?'),
                             help_text=_('Current or most recent degree you\'ve received'))
    level_of_study = forms.ChoiceField(choices=LEVELS_OF_STUDY, required=True, label=_('Level of Study'))

    first_time_volunteering = forms.TypedChoiceField(
        required=True,
        label=_('Have you volunteered in %s before?') % getattr(settings, 'HACKATHON_NAME'),
        initial=False,
        coerce=lambda x: x == 'True',
        choices=((False, _('No')), (True, _('Yes'))),
        widget=forms.RadioSelect
    )

    which_hack = forms.MultipleChoiceField(
        required=False,
        label=_('Which %s editions have you volunteered in') % getattr(settings, 'HACKATHON_NAME'),
        widget=forms.CheckboxSelectMultiple,
        choices=PREVIOUS_HACKS
    )

    night_shifts = forms.TypedChoiceField(
        required=True,
        label=_('Would you be ok doing night shifts?'),
        help_text=_('Volunteering during 2am - 5am'),
        coerce=lambda x: x == 'True',
        choices=((False, _('No')), (True, _('Yes'))),
        widget=forms.RadioSelect
    )

    origin = forms.CharField(max_length=300, label=_('From which city?'))

    country = forms.CharField(max_length=300, label=_('From which country are you joining us?'))

    attendance = forms.MultipleChoiceField(
        required=True,
        label=_('Which days will you attend %s?') % getattr(settings, 'HACKATHON_NAME'),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'inline'}),
        choices=HACK_DAYS
    )

    english_level = forms.ChoiceField(
        required=True,
        label=_('How confident are you speaking English?'),
        widget=forms.RadioSelect(attrs={'class': 'inline'}),
        choices=ENGLISH_LEVELS,
        help_text=_('1: I don\'t feel comfortable at all - 5: I\'m proficient '),
    )

    lennyface = forms.CharField(max_length=300, initial='-.-', label=_('Describe yourself with one "lenny face"?'),
                                help_text=mark_safe(
                                    _('Tip: you can choose one from <a href="https://textsmili.es/" target="_blank">textsmili.es</a>.')))

    friends = forms.CharField(
        required=False,
        label=_('If you\'re applying with friends, please mention their names.')
    )

    more_information = forms.CharField(
        required=False,
        label=_('Is there anything else we should know?')
    )

    description = forms.CharField(max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
                                  label=_('Why are you excited about %s?' % getattr(settings, 'HACKATHON_NAME')))

    discover_hack = forms.CharField(max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
                                    label=_('How did you discover %s?' % getattr(settings, 'HACKATHON_NAME')))

    class Meta(ApplicationForm.Meta):
        description = _('Volunteers make the event possible by assisting the hackers and preparing the '
                        'event site. By joining our team of volunteers, you will be able to see the inner workings of this event, meet amazing people, and partake in a great experience!')
        api_fields = {
            'country': {'url': static_lazy('data/countries.json'), 'restrict': True, 'others': True},
            'university': {'url': static_lazy('data/universities.json')},
            'degree': {'url': static_lazy('data/degrees.json')},
        }
