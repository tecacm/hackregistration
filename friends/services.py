from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from friends.emails import send_track_assigned_email, send_track_reassigned_email
from friends.models import FriendsCode


@dataclass
class TrackCandidate:
    code: str
    preferences: Tuple[str, str, str]
    members: List[FriendsCode]
    submitted_at: datetime


class TrackAssignmentService:
    def __init__(self, *, now: datetime | None = None):
        self.now = now or timezone.now()
        self.track_labels = dict(FriendsCode.TRACKS)

    def run(self, *, dry_run: bool = False, limit: int | None = None, send_emails: bool = True):
        grouped = self._collect_team_members()
        if not grouped:
            return [], []

        candidates, skipped = self._build_candidates(grouped)
        if not candidates:
            return [], skipped

        capacities: Dict[str, int | None] = dict(FriendsCode.track_capacity())
        counts = FriendsCode.track_counts()
        assignments = []

        for candidate in candidates:
            if limit is not None and len(assignments) >= limit:
                break

            track_choice, preference_used = self._pick_track(candidate.preferences, counts, capacities)
            if not track_choice:
                skipped.append({'team_code': candidate.code, 'reason': 'no_capacity'})
                continue

            label = self.track_labels.get(track_choice, track_choice)
            assignments.append({
                'team_code': candidate.code,
                'track_code': track_choice,
                'track_label': label,
                'preference_used': preference_used,
                'team_size': len(candidate.members),
                'submitted_at': candidate.submitted_at,
            })

            if dry_run:
                continue

            timestamp = self.now
            with transaction.atomic():
                FriendsCode.objects.filter(code=candidate.code).update(
                    track_assigned=track_choice,
                    track_assigned_date=timestamp,
                )

            if send_emails:
                recipients = self._collect_recipients(candidate.members)
                send_track_assigned_email(candidate.code, label, recipients)

        return assignments, skipped

    def _collect_team_members(self):
        base_qs = (
            FriendsCode.objects
            .filter(Q(track_assigned='') | Q(track_assigned__isnull=True))
            .exclude(track_pref_1__isnull=True)
            .exclude(track_pref_1='')
        )
        codes = list(base_qs.values_list('code', flat=True).distinct())
        if not codes:
            return {}

        members = (
            FriendsCode.objects
            .filter(code__in=codes)
            .select_related('user')
            .order_by('code', 'id')
        )
        grouped: Dict[str, List[FriendsCode]] = defaultdict(list)
        for member in members:
            grouped[member.code].append(member)
        return grouped

    def _build_candidates(self, grouped: Dict[str, List[FriendsCode]]):
        candidates: List[TrackCandidate] = []
        skipped = []
        for code, members in grouped.items():
            if not members:
                continue
            representative = members[0]
            preferences = (
                representative.track_pref_1 or '',
                representative.track_pref_2 or '',
                representative.track_pref_3 or '',
            )
            if not preferences[0]:
                skipped.append({'team_code': code, 'reason': 'missing_preferences'})
                continue
            if not representative.can_select_track():
                skipped.append({'team_code': code, 'reason': 'not_eligible'})
                continue
            submitted_at = representative.track_pref_submitted_at
            if not submitted_at:
                submitted_at = self._fallback_timestamp(members)
            candidates.append(
                TrackCandidate(
                    code=code,
                    preferences=preferences,
                    members=members,
                    submitted_at=submitted_at,
                )
            )
        candidates.sort(key=lambda c: (c.submitted_at, min(member.pk for member in c.members)))
        return candidates, skipped

    def _fallback_timestamp(self, members: List[FriendsCode]):
        timestamps = [member.track_pref_submitted_at for member in members if member.track_pref_submitted_at]
        if timestamps:
            return min(timestamps)
        user_dates = [getattr(member.user, 'date_joined', None) for member in members if getattr(member.user, 'date_joined', None)]
        if user_dates:
            return min(user_dates)
        return self.now

    def _pick_track(self, preferences: Tuple[str, str, str], counts: Dict[str, int], capacities: Dict[str, int | None]):
        for idx, preference in enumerate(preferences, start=1):
            if not preference:
                continue
            capacity = capacities.get(preference)
            current = counts.get(preference, 0)
            if capacity is None or current < capacity:
                counts[preference] = current + 1
                return preference, idx
        return None, None

    def _collect_recipients(self, members: List[FriendsCode]):
        return {member.user.email for member in members if getattr(member.user, 'email', None)}


class TrackReassignmentService:
    BANORTE_TRACKS = {
        FriendsCode.TRACK_SMART_CITIES,
        FriendsCode.TRACK_OPEN_INNOVATION,
    }

    def __init__(self, *, now: datetime | None = None, rng: random.Random | None = None):
        self.now = now or timezone.now()
        self.rng = rng or random.Random()
        self.track_labels = dict(FriendsCode.TRACKS)

    def run(self, *, dry_run: bool = False, send_emails: bool = True):
        capacities: Dict[str, int | None] = dict(FriendsCode.track_capacity())
        counts = FriendsCode.track_counts()
        reassignments = []
        skipped = []

        for track_code in sorted(self.BANORTE_TRACKS):
            capacity = capacities.get(track_code)
            if capacity is None:
                continue
            assigned_codes = list(
                FriendsCode.objects
                .filter(track_assigned=track_code)
                .values_list('code', flat=True)
                .distinct()
            )
            overflow = max(0, len(assigned_codes) - int(capacity))
            if overflow <= 0:
                continue
            overflow_codes = self._select_overflow_codes(assigned_codes, overflow)
            for team_code in overflow_codes:
                members = list(
                    FriendsCode.objects
                    .filter(code=team_code)
                    .select_related('user')
                    .order_by('id')
                )
                if not members:
                    continue
                representative = members[0]
                new_track, preference_used = self._choose_alternative_track(representative, counts, capacities)
                if not new_track:
                    skipped.append({'team_code': team_code, 'reason': 'no_alternative'})
                    continue

                counts[track_code] = max(counts.get(track_code, 0) - 1, 0)
                counts[new_track] = counts.get(new_track, 0) + 1
                record = {
                    'team_code': team_code,
                    'old_track': track_code,
                    'old_track_label': self.track_labels.get(track_code, track_code),
                    'new_track': new_track,
                    'new_track_label': self.track_labels.get(new_track, new_track),
                    'preference_used': preference_used,
                    'team_size': len(members),
                }
                reassignments.append(record)

                if dry_run:
                    continue

                timestamp = self.now
                FriendsCode.objects.filter(code=team_code).update(
                    track_assigned=new_track,
                    track_assigned_date=timestamp,
                )

                if send_emails:
                    recipients = self._collect_recipients(members)
                    send_track_reassigned_email(
                        team_code=team_code,
                        old_track_label=record['old_track_label'],
                        new_track_label=record['new_track_label'],
                        recipients=recipients,
                    )

        return reassignments, skipped

    def _select_overflow_codes(self, assigned_codes: List[str], overflow: int) -> List[str]:
        if overflow <= 0:
            return []
        if overflow >= len(assigned_codes):
            return list(assigned_codes)
        return self.rng.sample(assigned_codes, overflow)

    def _choose_alternative_track(self, representative: FriendsCode, counts: Dict[str, int], capacities: Dict[str, int | None]):
        preference_options = []
        for idx, pref in ((2, representative.track_pref_2), (3, representative.track_pref_3)):
            if pref and pref not in self.BANORTE_TRACKS:
                preference_options.append((idx, pref))
        if not preference_options:
            return None, None
        self.rng.shuffle(preference_options)
        for idx, track_code in preference_options:
            capacity = capacities.get(track_code)
            current = counts.get(track_code, 0)
            if capacity is None or current < capacity:
                return track_code, idx
        return None, None

    def _collect_recipients(self, members: List[FriendsCode]):
        return {member.user.email for member in members if getattr(member.user, 'email', None)}
