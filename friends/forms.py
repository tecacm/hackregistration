from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from app.mixins import BootstrapFormMixin
from application.models import Edition
from friends.models import FriendsCode, FriendsMergePoolEntry, CODE_LENGTH


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


class MatchmakingInviteForm(forms.Form):
    edition = forms.ModelChoiceField(
        queryset=Edition.objects.order_by('-order'),
        required=False,
        label=_('Edition'),
        help_text=_('Leave blank to use the current default edition.')
    )
    limit = forms.IntegerField(
        required=False,
        min_value=1,
        label=_('Limit'),
        help_text=_('Cap how many teams/solos are processed in this run.')
    )
    resend = forms.BooleanField(
        required=False,
        label=_('Include existing pool members'),
        help_text=_('Re-send invites to teams already marked as seeking a merge.')
    )
    preview_email = forms.EmailField(
        required=False,
        label=_('Preview email'),
        help_text=_('Optional: email a one-off preview using the first eligible team before sending the full run.')
    )


class MatchmakingRunForm(forms.Form):
    edition = forms.ModelChoiceField(
        queryset=Edition.objects.order_by('-order'),
        required=False,
        label=_('Edition'),
        help_text=_('Leave blank to use the current default edition.')
    )
    allow_size_three = forms.BooleanField(
        required=False,
        label=_('Allow size-three matches'),
        help_text=_('When enabled, leftover teams can be grouped into teams of three (deadline mode).')
    )
    trigger = forms.ChoiceField(
        required=False,
        choices=[('', _('Auto (default)'))] + list(FriendsMergePoolEntry.TRIGGER_CHOICES),
        label=_('Trigger label'),
        help_text=_('Optional label recorded on matched entries (auto/manual/deadline).')
    )

    def clean_trigger(self):
        trigger = self.cleaned_data.get('trigger')
        if not trigger:
            return FriendsMergePoolEntry.TRIGGER_AUTO
        return trigger


class TeamMembershipAddForm(forms.Form):
    email = forms.EmailField(
        label=_('Member email'),
        help_text=_('Email address of the participant to add or move.')
    )
    team_code = forms.CharField(
        label=_('Team code'),
        max_length=CODE_LENGTH,
        required=False,
        help_text=_('Existing team code. Leave blank to create a brand-new team for this member.')
    )
    move_if_exists = forms.BooleanField(
        required=False,
        initial=True,
        label=_('Move if already on a team'),
        help_text=_('If enabled, the member will be moved from their current team to the selected team.')
    )

    def clean(self):
        cleaned = super().clean()
        team_code = cleaned.get('team_code', '')
        if team_code:
            cleaned['team_code'] = team_code.strip()
        return cleaned


class TeamMembershipRemoveForm(forms.Form):
    email = forms.EmailField(
        label=_('Member email'),
        help_text=_('Email address of the participant to remove from their current team.')
    )
    confirm = forms.BooleanField(
        required=True,
        label=_('Confirm removal'),
        help_text=_('Tick to confirm you want to remove this member from their team.')
    )
