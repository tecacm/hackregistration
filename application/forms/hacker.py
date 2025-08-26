from django import forms
from django.conf import settings
from django.core.validators import RegexValidator
from django.urls import reverse_lazy
from django.templatetags.static import static
from django.utils.functional import lazy
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from user.choices import LEVELS_OF_STUDY

from application.forms.base import ApplicationForm, DEFAULT_YEAR, YEARS, EXTENSIONS
from application.validators import validate_file_extension, validate_file_size

static_lazy = lazy(static, str)


# This class is linked to the instance of ApplicationTypeConfig where name = 'Hacker'
class HackerForm(ApplicationForm):
    bootstrap_field_info = {
        '': {
            'fields': [
                {'name': 'university', 'space': 4}, {'name': 'degree', 'space': 4},
                {'name': 'lennyface', 'space': 4}, {'name': 'graduation_year', 'space': 8},
                # Full-width row for Level of Study
                {'name': 'level_of_study', 'space': 12},
            ]},
        _('Hackathons'): {
            'fields': [{'name': 'description', 'space': 6}, {'name': 'projects', 'space': 6},
                       {'name': 'first_timer', 'space': 12}, ]},
        _("Show us what you've built"): {
            'fields': [{'name': 'github', 'space': 6}, {'name': 'devpost', 'space': 6},
                       {'name': 'linkedin', 'space': 6}, {'name': 'site', 'space': 6},
                       {'name': 'resume', 'space': 12}, ],
            'description': 'Some of our sponsors may use this information for recruitment purposes, '
                           'so please include as much as you can.'},
        _('Traveling'): {
            'fields': [{'name': 'country', 'space': 6}, {'name': 'origin', 'space': 6}], }
    }

    phone_number = forms.CharField(validators=[RegexValidator(regex=r'^\+?1?\d{9,15}$')], required=True,
                                   help_text=_("Phone number must be entered in the format: +#########'. "
                                               "Up to 15 digits allowed."),
                                   widget=forms.TextInput(attrs={'placeholder': '+#########'}))

    origin = forms.CharField(max_length=300, label=_('From which city?'))

    country = forms.CharField(max_length=300, label=_('From which country are you joining us?'))

    # Is this your first hackathon?
    first_timer = forms.TypedChoiceField(
        required=True,
        label=_('Will %s be your first hackathon?' % getattr(settings, 'HACKATHON_NAME')),
        initial=False,
        coerce=lambda x: x == 'True',
        choices=((False, _('No')), (True, _('Yes'))),
        widget=forms.RadioSelect
    )

    # Random lenny face
    lennyface = forms.CharField(max_length=300, initial='-.-', label=_('Describe yourself with one "lenny face"?'),
                                help_text=mark_safe(
                                    _('Tip: you can choose one from <a href="https://textsmili.es/" target="_blank">textsmili.es</a>.')))

    # University
    graduation_year = forms.IntegerField(initial=DEFAULT_YEAR,
                                         widget=forms.RadioSelect(choices=YEARS, attrs={'class': 'inline'}),
                                         label=_('What year will you graduate?'))
    university = forms.CharField(max_length=300, label=_('What university do you study at?'),
                                 help_text=_('Current or most recent school you attended.'))
    degree = forms.CharField(max_length=300, label=_('What\'s your major/degree?'),
                             help_text=_('Current or most recent degree you\'ve received'))
    level_of_study = forms.ChoiceField(choices=LEVELS_OF_STUDY, required=True, label=_('Level of Study'))

    # URLs
    github = forms.URLField(required=False,
                            widget=forms.TextInput(attrs={'placeholder': 'https://github.com/johnBiene'}))
    devpost = forms.URLField(required=False,
                             widget=forms.TextInput(attrs={'placeholder': 'https://devpost.com/JohnBiene'}))
    linkedin = forms.URLField(required=False,
                              widget=forms.TextInput(attrs={'placeholder': 'https://www.linkedin.com/in/john_biene'}))
    site = forms.URLField(required=False, widget=forms.TextInput(attrs={'placeholder': 'https://biene.space'}))

    # Explain a little bit what projects have you done lately
    projects = forms.CharField(required=False, max_length=500, widget=forms.Textarea(attrs={'rows': 3}), help_text=_(
        'You can talk about past hackathons, personal projects, awards, etc. (we love links). '
        'Show us your passion! :D'), label=_('What projects have you worked on?'))

    # Why do you want to come to X?
    description = forms.CharField(max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
                                  label=_('Why are you excited about %s?' % getattr(settings, 'HACKATHON_NAME')))

    # CV info
    resume_share = forms.BooleanField(required=True, label=_(
        'I authorize %s to share my CV with this event\'s sponsors.' % (getattr(settings, 'HACKATHON_ORG'))))
    resume = forms.FileField(
        validators=[validate_file_extension(EXTENSIONS), validate_file_size(5)],
        label=_('Upload your resume'),
        help_text=_('Accepted format: PDF only. Max size: 5 MB'),
        widget=forms.ClearableFileInput(attrs={'accept': '.pdf,application/pdf'})
    )

    def get_policy_fields(self):
        # Reorder to show HackMTY-specific consents first (diet / resume share), then MLH consents
        base_fields = super().get_policy_fields()
        # base_fields currently: terms_and_conditions, diet_notice, mlh_data, mlh_emails
        by_name = {f['name']: f for f in base_fields}
        ordered_names = [
            'diet_notice',      # HackMTY catering data
            'resume_share',     # HackMTY resume sharing
            'terms_and_conditions',  # MLH Code of Conduct
            'mlh_data',         # MLH data sharing
            'mlh_emails',       # MLH optional emails
        ]
        # Ensure resume_share definition exists
        resume_share_field = {'name': 'resume_share', 'space': 12}
        result = []
        for name in ordered_names:
            if name == 'resume_share':
                result.append(resume_share_field)
            elif name in by_name:
                result.append(by_name[name])
        return result

    def get_hidden_edit_fields(self):
        hidden_fields = super().get_hidden_edit_fields()
        # On edit, do not require re-consent for resume sharing or re-uploading the resume.
        hidden_fields.extend(['resume_share', 'resume'])
        return hidden_fields

    class Meta(ApplicationForm.Meta):
        description = _('You will join a team and create a project during the event. '
                        'You can meet lots of new people and learn a lot, don\'t hesitate to apply!')
        api_fields = {
            'country': {'url': static_lazy('data/countries.json'), 'restrict': True, 'others': True},
            'university': {'url': static_lazy('data/universities.json')},
            'degree': {'url': static_lazy('data/degrees.json')},
        }
        icon_link = {
            'resume': 'bi bi-file-pdf-fill',
            'github': 'bi bi-github',
            'devpost': 'bi bi-collection-fill',
            'linkedin': 'bi bi-linkedin',
            'site': 'bi bi-globe',
        }
