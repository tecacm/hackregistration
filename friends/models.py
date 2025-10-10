import random
import string

from django.conf import settings
from django.db import models
from django.utils import timezone

from application.models import Application, Edition


CODE_LENGTH = getattr(settings, "FRIEND_CODE_LENGTH", 13)


def get_random_string():
    # With combination of lower, upper case and numbers
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(CODE_LENGTH))


class FriendsCode(models.Model):
    code = models.CharField(default=get_random_string, max_length=CODE_LENGTH)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    devpost_url = models.URLField(blank=True, null=True)
    # Track selection fields
    # Teams submit three ordered preferences; system assigns first available under capacity.
    # Capacity enforced per distinct team code per track.
    TRACK_INTERACTIVE_MEDIA = 'interactive_media'
    TRACK_SOCIAL_GOOD = 'social_good'
    TRACK_ALL_HEALTH = 'all_health'
    TRACK_FINTECH = 'fintech'
    TRACK_SMART_CITIES = 'smart_cities'
    TRACK_OPEN_INNOVATION = 'open_innovation'
    TRACKS = [
        (TRACK_INTERACTIVE_MEDIA, 'Interactive Media'),
        (TRACK_SOCIAL_GOOD, 'Social Good'),
        (TRACK_ALL_HEALTH, 'All Health'),
        (TRACK_FINTECH, 'FinTech'),
        (TRACK_SMART_CITIES, 'Smart Cities'),
        (TRACK_OPEN_INNOVATION, 'Open Innovation'),
    ]
    track_pref_1 = models.CharField(max_length=40, choices=TRACKS, blank=True)
    track_pref_2 = models.CharField(max_length=40, choices=TRACKS, blank=True)
    track_pref_3 = models.CharField(max_length=40, choices=TRACKS, blank=True)
    track_assigned = models.CharField(max_length=40, choices=TRACKS, blank=True)
    track_assigned_date = models.DateTimeField(blank=True, null=True)
    seeking_merge = models.BooleanField(default=False)
    seeking_merge_updated_at = models.DateTimeField(blank=True, null=True)

    STATUS_NOT_ALLOWED_TO_JOIN_TEAM = [
        Application.STATUS_CONFIRMED,
        Application.STATUS_INVITED,
        Application.STATUS_ATTENDED,
    ]

    def get_members(self):
        return FriendsCode.objects.filter(code=self.code)

    def is_closed(self):
        edition_pk = Edition.get_default_edition()
        return FriendsCode.objects.filter(
            code=self.code,
            user__application__edition_id=edition_pk,
            user__application__status__in=self.STATUS_NOT_ALLOWED_TO_JOIN_TEAM,
        ).exists()

    def is_closed_for_user(self, user):
        """A team is considered closed if there's a member with restricted status other than the requester."""
        edition_pk = Edition.get_default_edition()
        return FriendsCode.objects.filter(
            code=self.code,
            user__application__edition_id=edition_pk,
            user__application__status__in=self.STATUS_NOT_ALLOWED_TO_JOIN_TEAM,
        ).exclude(user=user).exists()

    def reached_max_capacity(self):
        friends_max_capacity = getattr(settings, 'FRIENDS_MAX_CAPACITY', None)
        if friends_max_capacity is not None and isinstance(friends_max_capacity, int):
            return FriendsCode.objects.filter(code=self.code).count() >= friends_max_capacity
        return False

    @classmethod
    def track_capacity(cls):
        return 63  # max teams per track

    @classmethod
    def track_counts(cls):
        # Count distinct team codes (groups) assigned per track for capacity enforcement
        return {
            t[0]: FriendsCode.objects.filter(track_assigned=t[0]).values('code').distinct().count()
            for t in cls.TRACKS
        }

    def can_select_track(self):
        # Eligibility: group full and every member confirmed or attended (current edition)
        friends_max_capacity = getattr(settings, 'FRIENDS_MAX_CAPACITY', None)
        if not friends_max_capacity:
            return False
        members = FriendsCode.objects.filter(code=self.code).select_related('user')
        if members.count() < friends_max_capacity:
            return False
        edition_pk = Edition.get_default_edition()
        from application.models import Application as AppModel
        statuses = list(
            AppModel.objects.filter(user__in=[m.user for m in members], edition_id=edition_pk)
            .values_list('status', flat=True)
        )
        allowed = {AppModel.STATUS_CONFIRMED, AppModel.STATUS_ATTENDED}
        return len(statuses) == members.count() and all(status in allowed for status in statuses)


class FriendsMembershipLog(models.Model):
    ACTION_ADD = 'add'
    ACTION_REMOVE = 'remove'
    ACTION_MOVE = 'move'
    ACTION_CHOICES = [
        (ACTION_ADD, 'Add'),
        (ACTION_REMOVE, 'Remove'),
        (ACTION_MOVE, 'Move'),
    ]
    timestamp = models.DateTimeField(default=timezone.now)
    admin_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='membership_actions')
    affected_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='team_membership_logs')
    action = models.CharField(max_length=8, choices=ACTION_CHOICES)
    from_code = models.CharField(max_length=20, blank=True)
    to_code = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.timestamp} {self.action} {self.affected_user_id} {self.from_code}->{self.to_code}"


class FriendsMergePoolEntry(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_MATCHED = 'matched'
    STATUS_REMOVED = 'removed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_MATCHED, 'Matched'),
        (STATUS_REMOVED, 'Removed'),
    ]

    TRIGGER_AUTO = 'auto'
    TRIGGER_MANUAL = 'manual'
    TRIGGER_DEADLINE = 'deadline'
    TRIGGER_CHOICES = [
        (TRIGGER_AUTO, 'Auto'),
        (TRIGGER_MANUAL, 'Manual'),
        (TRIGGER_DEADLINE, 'Deadline'),
    ]

    edition = models.ForeignKey(Edition, on_delete=models.CASCADE, related_name='merge_pool_entries')
    team_code = models.CharField(max_length=CODE_LENGTH)
    member_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    trigger = models.CharField(max_length=16, choices=TRIGGER_CHOICES, default=TRIGGER_AUTO)
    matched_team_code = models.CharField(max_length=CODE_LENGTH, blank=True)
    matched_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('edition', 'team_code')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.team_code} ({self.get_status_display()})"


class FriendsMergeEventLog(models.Model):
    EVENT_OPT_IN = 'opt_in'
    EVENT_MATCHED = 'matched'
    EVENT_REMOVED = 'removed'
    EVENT_NOTIFICATION = 'notified'
    EVENT_CHOICES = [
        (EVENT_OPT_IN, 'Opt-in'),
        (EVENT_MATCHED, 'Matched'),
        (EVENT_REMOVED, 'Removed from pool'),
        (EVENT_NOTIFICATION, 'Notification sent'),
    ]

    entry = models.ForeignKey(FriendsMergePoolEntry, on_delete=models.CASCADE, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='merge_events')
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.entry.team_code}: {self.get_event_type_display()}"
