from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import reverse

from application.models import Edition


class ReviewJudgeListTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.edition = Edition.objects.create(name='HackMTY', order=1)
        self.User = get_user_model()

        # Organizer account
        Group.objects.get_or_create(name='Organizer')
        self.organizer = self.User.objects.create_user(
            email='organizer@example.com',
            password='pass1234',
            first_name='Org',
            last_name='User',
            email_verified=True,
        )
        self.organizer.groups.add(Group.objects.get(name='Organizer'))

        # Judge user without existing application record
        Group.objects.get_or_create(name='Judge')
        self.judge = self.User.objects.create_user(
            email='judge@example.com',
            password='pass1234',
            first_name='Judgey',
            last_name='McJudge',
            email_verified=True,
            judge_type='technical',
        )
        self.judge.groups.add(Group.objects.get(name='Judge'))

    def test_judge_appears_in_review_list(self):
        self.client.force_login(self.organizer, backend='django.contrib.auth.backends.ModelBackend')
        response = self.client.get(reverse('application_list') + '?type=Judge')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'judge@example.com')
        self.assertContains(response, 'Technical / Engineering')

        # Tabs should include Judge
        tab_titles = [tab['title'] for tab in response.context['tabs']]
        self.assertIn('Judge', tab_titles)
