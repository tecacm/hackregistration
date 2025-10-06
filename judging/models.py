import secrets
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Avg, Count, F, Q
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _

from application.models import Edition
from friends.models import FriendsCode


def default_rubric_definition():
	"""Default rubric definition when organizers have not configured one yet."""
	return {
		"sections": [
			{
				"id": "innovation",
				"title": "Innovation",
				"weight": 0.25,
				"criteria": [
					{"id": "originality", "label": "Originality of the solution", "max_score": 6},
					{"id": "multidisciplinary", "label": "Intersection of disciplines/technologies", "max_score": 6},
				],
			},
			{
				"id": "technical",
				"title": "Technical Challenge",
				"weight": 0.25,
				"criteria": [
					{"id": "integration", "label": "Integration quality", "max_score": 6},
					{"id": "complexity", "label": "Overall technical complexity", "max_score": 6},
					{"id": "progress", "label": "Functional progress during the hackathon", "max_score": 6},
				],
			},
			{
				"id": "impact",
				"title": "Impact",
				"weight": 0.25,
				"criteria": [
					{"id": "inclusivity", "label": "Inclusive or social impact potential", "max_score": 6},
					{"id": "sustainability", "label": "Sustainable business or monetization strategy", "max_score": 6},
				],
			},
			{
				"id": "user_experience",
				"title": "User Experience",
				"weight": 0.15,
				"criteria": [
					{"id": "design", "label": "Visual design and ease of use", "max_score": 6},
					{"id": "clarity", "label": "Clarity of target user or market case", "max_score": 6},
				],
			},
			{
				"id": "presentation",
				"title": "Presentation",
				"weight": 0.1,
				"criteria": [
					{"id": "storytelling", "label": "Storytelling and narrative flow", "max_score": 6},
					{"id": "collaboration", "label": "Team collaboration and balance", "max_score": 6},
				],
			},
		]
	}


def generate_qr_slug(length: int = 8) -> str:
	alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
	return get_random_string(length, allowed_chars=alphabet)


class JudgeInviteCode(models.Model):
	code = models.CharField(max_length=128, unique=True)
	label = models.CharField(max_length=120, blank=True)
	notes = models.TextField(blank=True)
	is_active = models.BooleanField(default=True)
	max_uses = models.PositiveIntegerField(null=True, blank=True, help_text=_('Leave blank for unlimited uses.'))
	use_count = models.PositiveIntegerField(default=0)
	last_used_at = models.DateTimeField(blank=True, null=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['-is_active', 'code']
		verbose_name = _('judge invite code')
		verbose_name_plural = _('judge invite codes')

	def __str__(self):
		return self.label or self.code

	@property
	def remaining_uses(self):
		if self.max_uses is None:
			return None
		return max(self.max_uses - self.use_count, 0)

	@property
	def is_exhausted(self):
		return self.max_uses is not None and self.use_count >= self.max_uses

	@classmethod
	def active(cls):
		return cls.objects.filter(is_active=True)

	@classmethod
	def find_active(cls, code: str):
		return cls.active().filter(code__iexact=code).first()

	def mark_used(self):
		if not self.is_active or self.is_exhausted:
			raise ValidationError(_('This invite code is no longer available.'))
		updated = type(self).objects.filter(pk=self.pk, is_active=True).update(
			use_count=F('use_count') + 1,
			last_used_at=timezone.now(),
		)
		if not updated:
			raise ValidationError(_('Unable to register invite code usage. Please try another code.'))
		self.refresh_from_db(fields=['use_count', 'last_used_at'])
		if self.is_exhausted:
			type(self).objects.filter(pk=self.pk).update(is_active=False)
			self.is_active = False

	def save(self, *args, **kwargs):
		if self.max_uses is not None and self.max_uses == 0:
			raise ValidationError({'max_uses': _('Max uses must be greater than zero when provided.')})
		return super().save(*args, **kwargs)


class JudgingRubric(models.Model):
	edition = models.ForeignKey(Edition, on_delete=models.CASCADE, related_name="judging_rubrics")
	name = models.CharField(max_length=120, default="Default rubric")
	version = models.PositiveIntegerField(help_text=_('Increment every time you update the rubric definition.'))
	definition = models.JSONField(default=default_rubric_definition)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['-edition_id', '-version']
		unique_together = ('edition', 'version')

	def __str__(self):
		return f"{self.edition.name} v{self.version}"

	def clean(self):
		super().clean()
		sections = self.definition.get('sections', []) if isinstance(self.definition, dict) else []
		if not sections:
			raise ValidationError({'definition': _('At least one section is required in the rubric definition.')})
		total_weight = sum(section.get('weight', 0) for section in sections)
		if not 0.99 <= total_weight <= 1.01:
			raise ValidationError({'definition': _('Section weights must sum to 1.0 (±0.01).')})
		for section in sections:
			if not section.get('criteria'):
				raise ValidationError({'definition': _('Each section must include at least one criterion.')})
			for criterion in section.get('criteria', []):
				if criterion.get('max_score', 0) <= 0:
					raise ValidationError({'definition': _('Criterion max_score must be a positive number.')})

	@classmethod
	def active_for_edition(cls, edition: Edition):
		return cls.objects.filter(edition=edition, is_active=True).order_by('-version').first()


class JudgingProject(models.Model):
	edition = models.ForeignKey(Edition, on_delete=models.CASCADE, related_name='judging_projects')
	friends_code = models.ForeignKey(FriendsCode, on_delete=models.SET_NULL, blank=True, null=True, related_name='judging_projects')
	name = models.CharField(max_length=160)
	table_location = models.CharField(max_length=80, blank=True)
	track = models.CharField(max_length=80, blank=True)
	qr_slug = models.CharField(max_length=12, unique=True, editable=False)
	notes = models.TextField(blank=True)
	metadata = models.JSONField(blank=True, default=dict)
	is_active = models.BooleanField(default=True)
	is_public = models.BooleanField(default=False, help_text=_('Public projects appear in the released leaderboard.'))
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['name']
		unique_together = ('edition', 'friends_code')

	def __str__(self):
		return f"{self.name} ({self.edition.name})"

	def save(self, *args, **kwargs):
		if not self.qr_slug:
			slug = generate_qr_slug()
			while JudgingProject.objects.filter(qr_slug=slug).exists():
				slug = generate_qr_slug()
			self.qr_slug = slug
		if self.friends_code and self.edition_id is None:
			self.edition_id = Edition.get_default_edition()
		super().save(*args, **kwargs)

	@property
	def active_evaluations(self):
		return self.evaluations.filter(status__in=[JudgingEvaluation.STATUS_SUBMITTED, JudgingEvaluation.STATUS_RELEASED])

	def aggregate_scores(self):
		"""Return quick aggregates for dashboards."""
		stats = self.active_evaluations.aggregate(
			average=Avg('total_score'),
			count=Count('id'),
		)
		return {
			'average': float(stats['average']) if stats['average'] is not None else None,
			'count': stats['count'] or 0,
		}


class JudgingEvaluation(models.Model):
	STATUS_DRAFT = 'draft'
	STATUS_SUBMITTED = 'submitted'
	STATUS_RELEASED = 'released'
	STATUS_CHOICES = [
		(STATUS_DRAFT, _('Draft')),
		(STATUS_SUBMITTED, _('Submitted')),
		(STATUS_RELEASED, _('Released')),
	]

	project = models.ForeignKey(JudgingProject, on_delete=models.CASCADE, related_name='evaluations')
	judge = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='judging_evaluations')
	rubric = models.ForeignKey(JudgingRubric, on_delete=models.PROTECT, related_name='evaluations')
	scores = models.JSONField(default=dict)
	notes = models.TextField(blank=True)
	total_score = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
	status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)
	submitted_at = models.DateTimeField(blank=True, null=True)
	released_at = models.DateTimeField(blank=True, null=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['-updated_at']
		unique_together = ('project', 'judge', 'rubric')

	def __str__(self):
		return f"{self.project} — {self.judge.get_full_name() or self.judge.username}"

	def clean(self):
		super().clean()
		if self.project.edition_id != self.rubric.edition_id:
			raise ValidationError(_('Rubric edition mismatch for this project.'))

	def compute_total(self):
		definition = self.rubric.definition
		scores = self.scores or {}
		sections = definition.get('sections', []) if isinstance(definition, dict) else []
		weighted_total = Decimal('0')
		total_weight = Decimal('0')
		breakdown = {}
		for section in sections:
			weight = Decimal(str(section.get('weight', 0)))
			criteria = section.get('criteria', [])
			section_score = Decimal('0')
			section_max = Decimal('0')
			for criterion in criteria:
				criterion_id = criterion.get('id')
				if criterion_id is None:
					continue
				max_score = Decimal(str(criterion.get('max_score', 0)))
				if max_score <= 0:
					continue
				raw_value = Decimal(str(scores.get(criterion_id, 0) or 0))
				bounded_value = max(Decimal('0'), min(raw_value, max_score))
				section_score += bounded_value
				section_max += max_score
			if section_max > 0:
				normalized = section_score / section_max
				weighted_total += normalized * weight
				breakdown[section['id']] = float(round(normalized * Decimal('100'), 2))
			total_weight += weight
		if total_weight == 0:
			return Decimal('0'), {}
		normalized_total = (weighted_total / total_weight) * Decimal('100')
		return normalized_total.quantize(Decimal('0.01')), breakdown

	def submit(self):
		self.status = self.STATUS_SUBMITTED
		self.submitted_at = timezone.now()
		self.total_score, _ = self.compute_total()

	def release(self):
		if self.status != self.STATUS_SUBMITTED:
			raise ValidationError(_('Only submitted evaluations can be released.'))
		self.status = self.STATUS_RELEASED
		self.released_at = timezone.now()

	def save(self, *args, **kwargs):
		if self.status in {self.STATUS_SUBMITTED, self.STATUS_RELEASED} and not self.submitted_at:
			self.submitted_at = timezone.now()
		self.total_score, _ = self.compute_total()
		super().save(*args, **kwargs)


class EvaluationEventLog(models.Model):
	ACTION_CREATED = 'created'
	ACTION_UPDATED = 'updated'
	ACTION_SUBMITTED = 'submitted'
	ACTION_RELEASED = 'released'
	ACTION_CHOICES = [
		(ACTION_CREATED, _('Created')),
		(ACTION_UPDATED, _('Updated')),
		(ACTION_SUBMITTED, _('Submitted')),
		(ACTION_RELEASED, _('Released')),
	]

	evaluation = models.ForeignKey(JudgingEvaluation, on_delete=models.CASCADE, related_name='events')
	actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='judging_events')
	action = models.CharField(max_length=16, choices=ACTION_CHOICES)
	message = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return f"{self.evaluation_id}: {self.action}"


class JudgingReleaseWindow(models.Model):
	edition = models.ForeignKey(Edition, on_delete=models.CASCADE, related_name='judging_release_windows')
	opens_at = models.DateTimeField()
	closes_at = models.DateTimeField()
	is_active = models.BooleanField(default=True)
	released_at = models.DateTimeField(blank=True, null=True)
	released_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='judging_release_windows')
	csv_snapshot_path = models.CharField(max_length=255, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['-opens_at']
		constraints = [
			models.UniqueConstraint(fields=['edition'], condition=Q(is_active=True), name='unique_active_window_per_edition'),
		]

	def __str__(self):
		return f"{self.edition.name} window {self.opens_at:%Y-%m-%d %H:%M}"

	def clean(self):
		super().clean()
		if self.opens_at >= self.closes_at:
			raise ValidationError(_('Close time must be after open time.'))

	@property
	def is_open(self):
		now = timezone.now()
		return self.is_active and self.opens_at <= now <= self.closes_at

	def mark_released(self, user=None):
		self.released_at = timezone.now()
		self.released_by = user
		self.is_active = False
		self.save(update_fields=['released_at', 'released_by', 'is_active', 'updated_at'])
