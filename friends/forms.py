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

    track_pref_1 = forms.ChoiceField(label=_('First choice'), choices=[])
    track_pref_2 = forms.ChoiceField(label=_('Second choice'), choices=[])
    track_pref_3 = forms.ChoiceField(label=_('Third choice'), choices=[])

    def __init__(self, *args, **kwargs):
        track_counts = kwargs.pop('track_counts', None)
        track_capacity = kwargs.pop('track_capacity', None)
        super().__init__(*args, **kwargs)
        self._track_label_map = dict(FriendsCode.TRACKS)
        all_track_codes = [code for code, _ in FriendsCode.TRACKS]

        if track_counts is None:
            track_counts = FriendsCode.track_counts()
        if track_capacity is None:
            track_capacity = FriendsCode.track_capacity()

        self.track_counts = track_counts
        self.track_capacity = track_capacity

        self.full_track_codes = {
            code for code in all_track_codes
            if track_capacity.get(code) is not None
            and track_counts.get(code, 0) >= track_capacity.get(code, 0)
        }

        initial_codes = []
        for key in ('track_pref_1', 'track_pref_2', 'track_pref_3'):
            value = self.initial.get(key)
            if value in all_track_codes and value not in initial_codes:
                initial_codes.append(value)

        self.available_track_codes = []
        for code in all_track_codes:
            if code not in self.full_track_codes or code in initial_codes:
                self.available_track_codes.append(code)

        bound_only_codes = []
        if self.is_bound:
            for key in ('track_pref_1', 'track_pref_2', 'track_pref_3'):
                value = self.data.get(key)
                if value in all_track_codes and value not in self.available_track_codes:
                    self.available_track_codes.append(value)
                    bound_only_codes.append(value)

        self.open_track_codes = [code for code in all_track_codes if code not in self.full_track_codes]
        self._initial_code_set = set(initial_codes)
        self._allowed_codes = set(self.open_track_codes) | self._initial_code_set
        self._available_track_code_set = set(self.available_track_codes)
        self._bound_only_codes = set(bound_only_codes)
        self.has_minimum_preferences = len(self.open_track_codes) > 0
        self.required_choices = min(3, len(self.open_track_codes)) if self.open_track_codes else 0
        self.available_track_count = len(self.open_track_codes)

        placeholders = [self.PLACEHOLDER_1, self.PLACEHOLDER_2, self.PLACEHOLDER_3]
        field_names = ['track_pref_1', 'track_pref_2', 'track_pref_3']
        for idx, (field_name, placeholder) in enumerate(zip(field_names, placeholders), start=1):
            field = self.fields[field_name]
            field.choices = self._build_choices(placeholder)
            is_required = idx <= max(self.required_choices, 1) if self.has_minimum_preferences else False
            # When fewer tracks remain than slots, only require as many selections as there are available tracks
            if self.required_choices and idx > self.required_choices:
                is_required = False
            field.required = is_required
            if not is_required:
                field.widget.attrs.setdefault('data-optional', 'true')
            if not self.has_minimum_preferences:
                field.disabled = True
                field.required = False

    def _build_choices(self, placeholder_text):
        choices = [('', placeholder_text)]
        for code in self.available_track_codes:
            label = self._track_label_map.get(code)
            if label is not None:
                choices.append((code, label))
        return choices

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('track_pref_1')
        p2 = cleaned.get('track_pref_2')
        p3 = cleaned.get('track_pref_3')
        prefs = [p1, p2, p3]
        selected = [pref for pref in prefs if pref]
        required_count = self.required_choices if self.has_minimum_preferences else 0
        if required_count and len(selected) < required_count:
            raise forms.ValidationError(
                _('Please select %(count)s track preference%(plural)s.'),
                params={'count': required_count, 'plural': '' if required_count == 1 else 's'},
            )
        if len(set(selected)) != len(selected):
            raise forms.ValidationError(_('Track preferences must be different.'))
        unavailable = [track for track in prefs if track and track not in self._allowed_codes]
        if unavailable:
            labels = [self._track_label_map.get(code, code) for code in unavailable]
            raise forms.ValidationError(
                _('Some tracks are no longer available: %(tracks)s. Please choose a different track.'),
                params={'tracks': ', '.join(labels)},
            )
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
