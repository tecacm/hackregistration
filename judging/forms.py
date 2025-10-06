from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import JudgingProject, JudgingReleaseWindow, JudgingRubric


class ScoreForm(forms.Form):
    notes = forms.CharField(
        label=_('Quick notes'),
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
        required=False,
    )

    def __init__(self, rubric: JudgingRubric, *args, **kwargs):
        self.rubric = rubric
        super().__init__(*args, **kwargs)
        self._build_fields()

    def _build_fields(self):
        for section in self.rubric.definition.get('sections', []):
            for criterion in section.get('criteria', []):
                field_name = criterion['id']
                max_score = criterion.get('max_score', 6)
                self.fields[field_name] = forms.DecimalField(
                    label=criterion.get('label', field_name.replace('_', ' ').title()),
                    min_value=0,
                    max_value=max_score,
                    decimal_places=2,
                    max_digits=6,
                    widget=forms.NumberInput(attrs={'step': '0.5', 'class': 'form-control'}),
                )
                self.fields[field_name].section_id = section.get('id')
                self.fields[field_name].section_title = section.get('title')

    def cleaned_scores(self):
        scores = {
            key: float(value)
            for key, value in self.cleaned_data.items()
            if key != 'notes'
        }
        return scores


class ProjectSearchForm(forms.Form):
    query = forms.CharField(
        label=_('Search projects'),
        required=False,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': _('Search by name or keyword')},
        ),
    )
    track = forms.CharField(
        label=_('Track'),
        required=False,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': _('Track name')},
        ),
    )

    def filter_queryset(self, qs):
        query = self.cleaned_data.get('query')
        track = self.cleaned_data.get('track')
        if query:
            qs = qs.filter(name__icontains=query)
        if track:
            qs = qs.filter(track__iexact=track)
        return qs


class ReleaseWindowForm(forms.ModelForm):
    class Meta:
        model = JudgingReleaseWindow
        fields = ('opens_at', 'closes_at', 'is_active')
        widgets = {
            'opens_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'closes_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class ProjectForm(forms.ModelForm):
    class Meta:
        model = JudgingProject
        fields = ('name', 'track', 'table_location', 'friends_code', 'notes', 'metadata', 'is_active', 'is_public')
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'metadata': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_metadata(self):
        metadata = self.cleaned_data.get('metadata')
        if isinstance(metadata, dict):
            return metadata
        if not metadata:
            return {}
        try:
            import json

            return json.loads(metadata)
        except (json.JSONDecodeError, TypeError) as exc:
            raise forms.ValidationError(_('Metadata must be valid JSON.')) from exc
