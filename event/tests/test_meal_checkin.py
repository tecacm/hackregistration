from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from application.models import Application, ApplicationTypeConfig, Edition
from event.meals.models import Meal, Eaten


class MealCheckinTests(TestCase):
    def setUp(self):
        self.edition = Edition.objects.create(name='Test Edition', order=600)
        self.hacker_type = ApplicationTypeConfig.objects.create(name='Hacker')
        self.volunteer_type = ApplicationTypeConfig.objects.create(name='Volunteer')

        start = timezone.now() - timedelta(hours=1)
        end = timezone.now() + timedelta(hours=1)
        self.meal = Meal.objects.create(name='Lunch', kind='L', starts=start, ends=end, times=2)

        checker = get_user_model().objects.create_user('checker@example.com', password='pass12345')
        content_type, _ = ContentType.objects.get_or_create(app_label='event', model='event')
        perm, _ = Permission.objects.get_or_create(
            codename='can_checkin_meal',
            defaults={'name': 'Can checkin meal', 'content_type': content_type},
        )
        checker.user_permissions.add(perm)
        self.checker = checker
        self.client.force_login(checker, backend='django.contrib.auth.backends.ModelBackend')

        # Ensure edit permission exists for later tests
        self.edit_perm, _ = Permission.objects.get_or_create(
            codename='edit_meal',
            defaults={'name': 'Can edit meal', 'content_type': content_type},
        )

    def _create_attendee(self, email, application_type, status, qr_code):
        user = get_user_model().objects.create_user(email, password='pass12345')
        user.qr_code = qr_code
        user.save(update_fields=['qr_code'])
        Application.objects.create(
            user=user,
            type=application_type,
            edition=self.edition,
            status=status,
        )
        return user

    def test_meal_checkin_promotes_confirmed_hacker(self):
        attendee = self._create_attendee(
            'hacker@example.com',
            self.hacker_type,
            Application.STATUS_CONFIRMED,
            'HACKQR',
        )

        response = self.client.post(
            reverse('event:checkin_meal', kwargs={'mid': self.meal.id}),
            data={'qr_code': '  HACKQR  '},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get('status_promoted'))
        attendee.refresh_from_db()
        application = attendee.application_set.get(edition=self.edition, type=self.hacker_type)
        self.assertEqual(application.status, Application.STATUS_ATTENDED)
        self.assertEqual(Eaten.objects.filter(user=attendee, meal=self.meal).count(), 1)

    def test_meal_checkin_rejects_non_hacker(self):
        attendee = self._create_attendee(
            'volunteer@example.com',
            self.volunteer_type,
            Application.STATUS_CONFIRMED,
            'VOLQR',
        )

        response = self.client.post(
            reverse('event:checkin_meal', kwargs={'mid': self.meal.id}),
            data={'qr_code': 'VOLQR'},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn('Only hacker participants', payload['errors'][0])
        attendee.refresh_from_db()
        application = attendee.application_set.get(edition=self.edition, type=self.volunteer_type)
        self.assertEqual(application.status, Application.STATUS_CONFIRMED)
        self.assertEqual(Eaten.objects.filter(user=attendee, meal=self.meal).count(), 0)

    def test_meal_edit_permissions_accept_list(self):
        editor = get_user_model().objects.create_user('editor@example.com', password='pass12345')
        editor.user_permissions.add(self.edit_perm)
        self.client.force_login(editor, backend='django.contrib.auth.backends.ModelBackend')

        response = self.client.get(reverse('event:edit_meal', kwargs={'mid': self.meal.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.meal.name)
