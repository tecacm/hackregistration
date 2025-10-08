from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

from django.db import transaction

from application.models import Edition
from friends.models import FriendsCode

from .models import (
    EvaluationEventLog,
    JudgingEvaluation,
    JudgingProject,
    JudgingReleaseWindow,
    JudgingRubric,
)


@dataclass
class EvaluationResult:
    evaluation: JudgingEvaluation
    created: bool


def upsert_evaluation(
    project: JudgingProject,
    judge,
    scores: Dict[str, float],
    notes: str = "",
    *,
    submit: bool = False,
    rubric: JudgingRubric | None = None,
) -> EvaluationResult:
    """Create or update a judging evaluation in a single transaction."""
    rubric = rubric or JudgingRubric.active_for_edition(project.edition, track=project.track)
    if rubric is None:
        raise ValueError("No active rubric is configured for this edition.")

    with transaction.atomic():
        evaluation, created = JudgingEvaluation.objects.select_for_update().get_or_create(
            project=project,
            judge=judge,
            rubric=rubric,
            defaults={'scores': scores, 'notes': notes},
        )
        if not created:
            evaluation.scores = scores
            evaluation.notes = notes
        if submit:
            evaluation.submit()
        evaluation.save()
        log_action = EvaluationEventLog.ACTION_CREATED if created else EvaluationEventLog.ACTION_UPDATED
        EvaluationEventLog.objects.create(
            evaluation=evaluation,
            actor=judge,
            action=log_action,
            message="Submitted" if submit else "Saved",
        )
    return EvaluationResult(evaluation=evaluation, created=created)


def release_evaluations(window: JudgingReleaseWindow, *, actor=None) -> int:
    """Mark submitted evaluations in the window's edition as released."""
    qs = JudgingEvaluation.objects.filter(
        project__edition=window.edition,
        status=JudgingEvaluation.STATUS_SUBMITTED,
    )
    count = 0
    with transaction.atomic():
        for evaluation in qs.select_for_update():
            evaluation.release()
            evaluation.save(update_fields=['status', 'released_at', 'submitted_at', 'total_score', 'updated_at'])
            EvaluationEventLog.objects.create(
                evaluation=evaluation,
                actor=actor,
                action=EvaluationEventLog.ACTION_RELEASED,
                message="Released via window",
            )
            count += 1
        window.mark_released(actor)
    return count


def build_leaderboard(edition: Edition, *, limit: int | None = None) -> Iterable[Tuple[JudgingProject, dict]]:
    projects = (
        JudgingProject.objects.filter(edition=edition, is_active=True)
        .prefetch_related('evaluations__judge')
        .order_by('name')
    )
    for project in projects:
        totals = project.aggregate_scores()
        if totals['count'] == 0:
            continue
        yield project, totals
        if limit is not None:
            limit -= 1
            if limit <= 0:
                break


def export_csv(edition: Edition) -> io.StringIO:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        'Project',
        'Track',
        'Table',
        'Average score',
        'Total evaluations',
        'Judges',
    ])
    for project, totals in build_leaderboard(edition):
        judge_names = []
        for evaluation in project.evaluations.all():
            if evaluation.status not in {
                JudgingEvaluation.STATUS_SUBMITTED,
                JudgingEvaluation.STATUS_RELEASED,
            }:
                continue
            judge = evaluation.judge
            if judge is None:
                continue
            display_name = (
                judge.get_full_name() or getattr(judge, 'get_short_name', lambda: '')() or judge.username
            )
            status_suffix = '' if evaluation.status == JudgingEvaluation.STATUS_RELEASED else f" ({evaluation.get_status_display()})"
            judge_names.append(f"{display_name}{status_suffix}")
        unique_judges = list(dict.fromkeys(judge_names))
        unique_judges.sort(key=str.casefold)
        judges_cell = '; '.join(unique_judges)
        writer.writerow([
            project.name,
            project.track,
            project.table_location,
            totals['average'],
            totals['count'],
            judges_cell,
        ])
    buffer.seek(0)
    return buffer


def judge_summary(judge) -> Dict[str, int]:
    qs = JudgingEvaluation.objects.filter(judge=judge)
    return {
        'drafts': qs.filter(status=JudgingEvaluation.STATUS_DRAFT).count(),
        'submitted': qs.filter(status=JudgingEvaluation.STATUS_SUBMITTED).count(),
        'released': qs.filter(status=JudgingEvaluation.STATUS_RELEASED).count(),
    }


def _team_members_with_metadata(team_code: str):
    members = []
    entries = FriendsCode.objects.filter(code=team_code).select_related('user')
    for entry in entries:
        user = entry.user
        if not user:
            continue
        members.append({
            'id': user.id,
            'name': user.get_full_name() or user.email,
            'email': user.email,
            'qr_code': user.qr_code,
        })
    return members


def ensure_project_for_team_member(user) -> JudgingProject | None:
    """Fetch or lazily create a JudgingProject for the participant's team."""
    membership = FriendsCode.objects.filter(user=user).first()
    if membership is None:
        return None

    team_code = membership.code
    canonical = (
        FriendsCode.objects
        .filter(code=team_code)
        .order_by('id')
        .select_related('user')
        .first()
    )
    if canonical is None:
        return None

    edition_id = Edition.get_default_edition()
    metadata = {
        'team_code': team_code,
        'devpost_url': canonical.devpost_url,
        'members': _team_members_with_metadata(team_code),
    }
    defaults = {
        'name': canonical.devpost_url.rstrip('/').split('/')[-1].replace('-', ' ').title()
        if canonical.devpost_url else f"Team {team_code}",
        'track': canonical.track_assigned or '',
        'friends_code': canonical,
        'metadata': metadata,
    }

    project, created = JudgingProject.objects.get_or_create(
        edition_id=edition_id,
        friends_code=canonical,
        defaults=defaults,
    )

    # Ensure metadata stays fresh if team composition or links change.
    fields_to_update = []
    desired_track = canonical.track_assigned or ''
    if project.track != desired_track:
        project.track = desired_track
        fields_to_update.append('track')

    if project.metadata != metadata:
        project.metadata = metadata
        fields_to_update.append('metadata')

    if created and metadata.get('devpost_url') and not project.notes:
        project.notes = metadata['devpost_url']
        fields_to_update.append('notes')

    if fields_to_update:
        fields_to_update.append('updated_at')
        project.save(update_fields=fields_to_update)

    return project
