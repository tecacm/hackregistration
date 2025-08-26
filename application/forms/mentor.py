from django import forms
from django.conf import settings
from django.templatetags.static import static
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy as _

from user.choices import LEVELS_OF_STUDY

from application.forms.base import ApplicationForm

static_lazy = lazy(static, str)


class MentorForm(ApplicationForm):
    bootstrap_field_info = {
        '': {'fields': [
            {'name': 'university', 'space': 6}, {'name': 'degree', 'space': 6},
            {'name': 'country', 'space': 6}, {'name': 'origin', 'space': 6}, {'name': 'study_work', 'space': 6},
            {'name': 'company', 'space': 6, 'visible': {'study_work': 'Work'}},
            {'name': 'level_of_study', 'space': 12},
        ]},
        'Hackathons': {
            'fields': [{'name': 'first_timer', 'space': 4},
                       {'name': 'previous_roles', 'space': 4, 'visible': {'first_timer': 'False'}},
                       {'name': 'more_information', 'space': 12}],
            'description': _('Tell us a bit about your experience and preferences in this type of event.')},
    }

    university = forms.CharField(max_length=300, label=_('What university do you study at?'),
                                 help_text=_('Current or most recent school you attended.'))

    degree = forms.CharField(max_length=300, label=_('What\'s your major/degree?'),
                             help_text=_('Current or most recent degree you\'ve received'))
    level_of_study = forms.ChoiceField(choices=LEVELS_OF_STUDY, required=True, label=_('Level of Study'))

    origin = forms.CharField(max_length=300, label=_('From which city?'))

    country = forms.CharField(max_length=300, label=_('From which country are you joining us?'))

    study_work = forms.TypedChoiceField(
        required=True,
        label=_('Are you studying or working?'),
        choices=(('Study', _('Studying')), ('Work', _('Working'))),
        widget=forms.RadioSelect(attrs={'class': 'inline'})
    )

    company = forms.CharField(
        required=False,
        help_text=_('Current or most recent company you worked at.'),
        label=_('Where are you working?')
    )

    first_timer = forms.TypedChoiceField(
        required=True,
        label=_('Will %s be your first hackathon?' % getattr(settings, 'HACKATHON_NAME')),
        initial=True,
        coerce=lambda x: x == 'True',
        choices=((False, _('No')), (True, _('Yes'))),
        widget=forms.RadioSelect
    )

    previous_roles = forms.MultipleChoiceField(
        required=False,
        label=_('Did you participate as a hacker, mentor, or volunteer?'),
        widget=forms.CheckboxSelectMultiple,
        choices=(('Hacker', _('Hacker')), ('Mentor', _('Mentor')), ('Volunteer', _('Volunteer')))
    )

    more_information = forms.CharField(
        required=False,
        label=_('Is there anything else we should know?')
    )

    class Meta(ApplicationForm.Meta):
        description = _(
            'Help and motivate hackers with your knowledge. Whether you are passionate about technology '
            'or graduated over a year ago, applying as a mentor is a great opportunity!'
        )
        api_fields = {
            'country': {'url': static_lazy('data/countries.json'), 'restrict': True, 'others': True},
            'university': {'url': static_lazy('data/universities.json')},
            'degree': {'url': static_lazy('data/degrees.json')},
        }
