from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from app.mixins import BootstrapFormMixin
from friends.models import FriendsCode


class FriendsForm(BootstrapFormMixin, forms.Form):
    bootstrap_field_info = {'': {'fields': [{'name': 'friends_code', 'space': 12}, ]}}

    friends_code = forms.CharField(label=_('Friends\' code'), max_length=getattr(settings, "FRIEND_CODE_LENGTH", 13),
                                   required=False)


class DevpostForm(BootstrapFormMixin, forms.Form):
    bootstrap_field_info = {'': {'fields': [{'name': 'devpost_url', 'space': 12}, ]}}
    devpost_url = forms.URLField(label=_('Devpost project URL'), required=True)

    def clean_devpost_url(self):
        url = self.cleaned_data['devpost_url']
        # Accept devpost.com and *.devpost.com
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ''
        if not (host == 'devpost.com' or host.endswith('.devpost.com')):
            raise forms.ValidationError(_('Please provide a valid Devpost URL.'))
        return url


class TrackPreferenceForm(BootstrapFormMixin, forms.Form):
    bootstrap_field_info = {'': {'fields': [
        {'name': 'track_pref_1', 'space': 12},
        {'name': 'track_pref_2', 'space': 12},
        {'name': 'track_pref_3', 'space': 12},
    ]}}

    # Prepend placeholder option to choices so initial render shows a distinct prompt
    PLACEHOLDER_1 = _('Select first track')
    PLACEHOLDER_2 = _('Select second track')
    PLACEHOLDER_3 = _('Select third track')

    def _with_placeholder(self, placeholder_text):
        return [('', placeholder_text)] + list(FriendsCode.TRACKS)

    track_pref_1 = forms.ChoiceField(label=_('First choice'), choices=[])
    track_pref_2 = forms.ChoiceField(label=_('Second choice'), choices=[])
    track_pref_3 = forms.ChoiceField(label=_('Third choice'), choices=[])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['track_pref_1'].choices = self._with_placeholder(self.PLACEHOLDER_1)
        self.fields['track_pref_2'].choices = self._with_placeholder(self.PLACEHOLDER_2)
        self.fields['track_pref_3'].choices = self._with_placeholder(self.PLACEHOLDER_3)
        # Require explicit selection (empty not allowed)
        self.fields['track_pref_1'].required = True
        self.fields['track_pref_2'].required = True
        self.fields['track_pref_3'].required = True

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('track_pref_1')
        p2 = cleaned.get('track_pref_2')
        p3 = cleaned.get('track_pref_3')
        prefs = [p1, p2, p3]
        if '' in prefs or None in prefs:
            raise forms.ValidationError(_('Please select all three track preferences.'))
        if len({p for p in prefs if p}) != 3:
            raise forms.ValidationError(_('Track preferences must be three different tracks.'))
        return cleaned
