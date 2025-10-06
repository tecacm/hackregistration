from __future__ import annotations

import json
import os
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from application.models import Application, ApplicationTypeConfig, Edition
from friends.models import FriendsCode

from .models import JudgingEvaluation, JudgingProject, JudgingReleaseWindow, JudgingRubric, JudgeInviteCode
from .services import release_evaluations, upsert_evaluation


class JudgingTestCase(TestCase):
	def setUp(self):
		super().setUp()
		self.edition = Edition.objects.create(name='HackMTY', order=1)
		self.rubric = JudgingRubric.objects.create(edition=self.edition, name='Expo', version=1)
		self.project = JudgingProject.objects.create(edition=self.edition, name='Project Atlas')
		self.judge = self._create_user('judge@example.com', groups=['Judge'])
		self.organizer = self._create_user('organizer@example.com', is_staff=True)

	def _create_user(self, email: str, *, is_staff: bool = False, groups: list[str] | None = None):
		User = get_user_model()
		user = User.objects.create_user(email=email, password='pass1234', is_staff=is_staff)
		if groups:
			for group_name in groups:
				group, _ = Group.objects.get_or_create(name=group_name)
				user.groups.add(group)
		return user


class JudgingEvaluationTests(JudgingTestCase):
	def test_compute_total_uses_weighted_average(self):
		scores = {
			criterion['id']: criterion['max_score']
			for section in self.rubric.definition['sections']
			for criterion in section['criteria']
		}
		evaluation = upsert_evaluation(
			project=self.project,
			judge=self.judge,
			scores=scores,
			submit=True,
			rubric=self.rubric,
		).evaluation
		self.assertEqual(evaluation.status, JudgingEvaluation.STATUS_SUBMITTED)
		self.assertEqual(float(evaluation.total_score), 100.0)

	def test_release_evaluations_marks_released(self):
		scores = {
			section['criteria'][0]['id']: section['criteria'][0]['max_score']
			for section in self.rubric.definition['sections']
		}
		evaluation = upsert_evaluation(
			project=self.project,
			judge=self.judge,
			scores=scores,
			submit=True,
			rubric=self.rubric,
		).evaluation
		window = JudgingReleaseWindow.objects.create(
			edition=self.edition,
			opens_at=timezone.now() - timezone.timedelta(hours=1),
			closes_at=timezone.now() + timezone.timedelta(hours=2),
		)
		released = release_evaluations(window, actor=self.organizer)
		evaluation.refresh_from_db()
		window.refresh_from_db()

		self.assertEqual(released, 1)
		self.assertEqual(evaluation.status, JudgingEvaluation.STATUS_RELEASED)
		self.assertFalse(window.is_active)
		self.assertIsNotNone(window.released_at)


class JudgingViewTests(JudgingTestCase):
	def setUp(self):
		super().setUp()
		self.client = Client()

	def test_dashboard_requires_login(self):
		response = self.client.get(reverse('judging:dashboard'))
		self.assertEqual(response.status_code, 302)

	def test_judge_can_view_dashboard(self):
		self.client.force_login(self.judge, backend='django.contrib.auth.backends.ModelBackend')
		response = self.client.get(reverse('judging:dashboard'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Judging dashboard')

	def test_scoring_flow_submits_scores(self):
		self.client.force_login(self.judge, backend='django.contrib.auth.backends.ModelBackend')
		JudgingReleaseWindow.objects.create(
			edition=self.edition,
			opens_at=timezone.now() - timezone.timedelta(hours=1),
			closes_at=timezone.now() + timezone.timedelta(hours=1),
		)
		url = reverse('judging:score', args=[self.project.pk])
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)

		post_data = {'notes': 'Great build!', 'action': 'submit'}
		for section in self.rubric.definition['sections']:
			for criterion in section['criteria']:
				post_data[criterion['id']] = criterion['max_score']

		response = self.client.post(url, post_data, follow=True)
		self.assertEqual(response.status_code, 200)
		evaluation = JudgingEvaluation.objects.get(project=self.project, judge=self.judge)
		self.assertEqual(evaluation.status, JudgingEvaluation.STATUS_SUBMITTED)


class JudgingScanTests(JudgingTestCase):
	def setUp(self):
		super().setUp()
		self.client = Client()

	def test_scan_creates_project_from_team_qr(self):
		self.client.force_login(self.judge, backend='django.contrib.auth.backends.ModelBackend')
		member = self._create_user('team@example.com')
		member.qr_code = 'TEAMQR123'
		member.save(update_fields=['qr_code'])
		other = self._create_user('teammate@example.com')
		FriendsCode.objects.create(user=member, code='TEAM-001', devpost_url='https://devpost.com/projects/team-001', track_assigned=FriendsCode.TRACK_FINTECH)
		FriendsCode.objects.create(user=other, code='TEAM-001')

		url = reverse('judging:scan', args=[member.qr_code])
		response = self.client.get(url)
		self.assertEqual(response.status_code, 302)
		project = JudgingProject.objects.get(friends_code__code='TEAM-001')
		self.assertIn(str(project.pk), response['Location'])
		self.assertEqual(project.track, FriendsCode.TRACK_FINTECH)
		self.assertEqual(project.metadata['team_code'], 'TEAM-001')
		self.assertEqual(len(project.metadata['members']), 2)

	def test_scan_accepts_encoded_participant_id(self):
		self.client.force_login(self.judge, backend='django.contrib.auth.backends.ModelBackend')
		member = self._create_user('encoded@example.com')
		teammate = self._create_user('encoded-teammate@example.com')
		FriendsCode.objects.create(user=member, code='TEAM-ENC', devpost_url='https://devpost.com/projects/team-enc', track_assigned=FriendsCode.TRACK_ALL_HEALTH)
		FriendsCode.objects.create(user=teammate, code='TEAM-ENC')

		slug = member.get_encoded_pk()
		response = self.client.get(reverse('judging:scan', args=[slug]))
		self.assertEqual(response.status_code, 302)
		project = JudgingProject.objects.get(friends_code__code='TEAM-ENC')
		self.assertIn(str(project.pk), response['Location'])
class JudgingImportCommandTests(JudgingTestCase):
	def test_import_rubric_command_creates_active_rubric(self):
		payload = {
			"sections": [
				{
					"id": "df_section",
					"title": "DataFrame Section",
					"weight": 1.0,
					"criteria": [
						{"id": "criterion_one", "label": "Criterion One", "max_score": 6},
					],
				}
			]
		}
		with tempfile.NamedTemporaryFile('w+', suffix='.json', delete=False) as handle:
			json.dump(payload, handle)
			handle.flush()
			tmp_path = handle.name
		try:
			call_command(
				'import_rubric',
				self.edition.pk,
				tmp_path,
				name='DF Rubric',
				activate=True,
			)
		finally:
			os.unlink(tmp_path)

		rubrics = JudgingRubric.objects.filter(edition=self.edition).order_by('version')
		self.assertEqual(rubrics.count(), 2)
		previous, imported = rubrics
		self.assertFalse(previous.is_active)
		self.assertTrue(imported.is_active)
		self.assertEqual(imported.name, 'DF Rubric')
		self.assertEqual(imported.version, previous.version + 1)
		self.assertEqual(len(imported.definition['sections']), 1)


class JudgeSignupTests(TestCase):
	def setUp(self):
		self.client = Client()
		self.edition = Edition.objects.create(name='HackMTY', order=1)
		ApplicationTypeConfig.objects.update_or_create(
			name='Judge',
			defaults={
				'vote': False,
				'dubious': False,
				'auto_confirm': True,
				'compatible_with_others': True,
				'create_user': False,
				'hidden': True,
			},
		)
		self.invite = JudgeInviteCode.objects.create(code='SECRET123', label='Expo Judges')

	def test_signup_page_renders(self):
		response = self.client.get(reverse('judge_register'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Join the judging team')
		self.assertContains(response, 'Invite code')

	def test_signup_creates_judge_and_redirects_to_dashboard(self):
		payload = {
			'first_name': 'Jamie',
			'last_name': 'Judge',
			'email': 'jamie@example.com',
			'judge_type': 'technical',
			'password1': 'SecurePass!123',
			'password2': 'SecurePass!123',
			'invite_code': 'SECRET123',
			'terms_and_conditions': 'on',
		}
		response = self.client.post(reverse('judge_register'), payload, follow=True)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Judging dashboard')
		self.assertTrue(response.context['user'].is_authenticated)
		self.assertEqual(response.context['user'].email, 'jamie@example.com')
		User = get_user_model()
		user = User.objects.get(email='jamie@example.com')
		self.assertTrue(user.groups.filter(name='Judge').exists())
		self.assertEqual(user.judge_type, 'technical')
		application = Application.objects.get(user=user, type__name='Judge', edition=self.edition)
		self.assertEqual(application.status, Application.STATUS_CONFIRMED)
		self.assertEqual(application.form_data.get('judge_type'), 'technical')
		self.invite.refresh_from_db()
		self.assertEqual(self.invite.use_count, 1)

	def test_signup_rejects_invalid_invite_code(self):
		payload = {
			'first_name': 'Taylor',
			'last_name': 'Tester',
			'email': 'taylor@example.com',
			'judge_type': 'business',
			'password1': 'SecurePass!123',
			'password2': 'SecurePass!123',
			'invite_code': 'WRONGCODE',
			'terms_and_conditions': 'on',
		}
		response = self.client.post(reverse('judge_register'), payload)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'That invite code is not valid')
		User = get_user_model()
		self.assertFalse(User.objects.filter(email='taylor@example.com').exists())
