from django.contrib import admin

from .models import (
	EvaluationEventLog,
	JudgingEvaluation,
	JudgingProject,
	JudgingReleaseWindow,
	JudgingRubric,
)


@admin.register(JudgingRubric)
class JudgingRubricAdmin(admin.ModelAdmin):
	list_display = ('edition', 'name', 'version', 'is_active', 'created_at')
	list_filter = ('edition', 'is_active')
	search_fields = ('name',)
	readonly_fields = ('created_at', 'updated_at')


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
