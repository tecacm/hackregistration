from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
	EvaluationEventLog,
    JudgeInviteCode,
	JudgingEvaluation,
	JudgingProject,
	JudgingReleaseWindow,
	JudgingRubric,
)


class JudgingRubricAdminForm(forms.ModelForm):
	track = forms.ChoiceField(required=False)

	class Meta:
		model = JudgingRubric
		fields = '__all__'

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['track'].choices = self._build_track_choices()
		self.fields['track'].help_text = JudgingRubric._meta.get_field('track').help_text

	def _build_track_choices(self):
		from friends.models import FriendsCode

		blank_choice = ('', _('General (no track)'))
		friend_tracks = list(FriendsCode.TRACKS)
		friend_lookup = {value: label for value, label in friend_tracks}

		existing_tracks = set()
		existing_tracks.update(
			track.strip()
			for track in JudgingProject.objects.order_by().values_list('track', flat=True).distinct()
			if track and track.strip()
		)
		existing_tracks.update(
			track.strip()
			for track in JudgingRubric.objects.order_by().values_list('track', flat=True).distinct()
			if track and track.strip()
		)

		choices = [blank_choice]
		for value, label in friend_tracks:
			choices.append((value, label))
			existing_tracks.discard(value)

		current_value = (self.instance.track or '').strip()
		if current_value:
			existing_tracks.add(current_value)

		for track in sorted(existing_tracks, key=lambda item: item.lower()):
			label = friend_lookup.get(track, track)
			choices.append((track, label))

		return choices

	def clean_track(self):
		return (self.cleaned_data.get('track') or '').strip()


@admin.register(JudgingRubric)
class JudgingRubricAdmin(admin.ModelAdmin):
	list_display = ('edition', 'track', 'name', 'version', 'is_active', 'created_at')
	list_filter = ('edition', 'track', 'is_active')
	search_fields = ('name', 'track')
	readonly_fields = ('created_at', 'updated_at')
	form = JudgingRubricAdminForm


@admin.register(JudgingProject)
class JudgingProjectAdmin(admin.ModelAdmin):
	list_display = ('name', 'edition', 'track', 'table_location', 'is_active', 'is_public')
	list_filter = ('edition', 'track', 'is_active', 'is_public')
	search_fields = ('name', 'friends_code__code', 'qr_slug')
	readonly_fields = ('qr_slug', 'created_at', 'updated_at')


@admin.register(JudgingEvaluation)
class JudgingEvaluationAdmin(admin.ModelAdmin):
	list_display = ('project', 'judge', 'status', 'total_score', 'submitted_at', 'released_at')
	list_filter = ('status', 'project__edition')
	search_fields = ('project__name', 'judge__email', 'judge__username')
	readonly_fields = ('total_score', 'created_at', 'updated_at')


@admin.register(EvaluationEventLog)
class EvaluationEventLogAdmin(admin.ModelAdmin):
	list_display = ('evaluation', 'action', 'actor', 'created_at')
	list_filter = ('action',)
	search_fields = ('evaluation__project__name', 'actor__email')
	readonly_fields = ('created_at',)


@admin.register(JudgingReleaseWindow)
class JudgingReleaseWindowAdmin(admin.ModelAdmin):
	list_display = ('edition', 'opens_at', 'closes_at', 'is_active', 'released_at')
	list_filter = ('edition', 'is_active')
	readonly_fields = ('released_at', 'released_by', 'created_at', 'updated_at')


@admin.register(JudgeInviteCode)
class JudgeInviteCodeAdmin(admin.ModelAdmin):
	list_display = ('code', 'label', 'is_active', 'max_uses', 'use_count', 'remaining_display', 'last_used_at', 'updated_at')
	list_filter = ('is_active',)
	search_fields = ('code', 'label', 'notes')
	readonly_fields = ('use_count', 'last_used_at', 'created_at', 'updated_at', 'remaining_display')
	fieldsets = (
		(None, {'fields': ('code', 'label', 'notes')}),
		(_('Usage controls'), {'fields': ('is_active', 'max_uses', 'use_count', 'remaining_display', 'last_used_at')}),
		(_('Timestamps'), {'fields': ('created_at', 'updated_at')}),
	)

	@admin.display(description=_('Remaining uses'))
	def remaining_display(self, obj):
		return obj.remaining_uses if obj.remaining_uses is not None else _('Unlimited')
