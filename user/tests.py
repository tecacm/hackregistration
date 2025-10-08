from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from user.forms import UserProfileForm


class UserProfileFormJudgeTypeTests(TestCase):
    def test_judge_type_hidden_for_new_applicants(self):
        form = UserProfileForm()
        self.assertNotIn('judge_type', form.fields)

    def test_judge_type_visible_for_judges(self):
        group, _ = Group.objects.get_or_create(name='Judge')
        User = get_user_model()
        judge = User.objects.create_user(
            email='judge@example.com',
            password='pass1234',
            first_name='Judgey',
            last_name='McJudge',
            email_verified=True,
        )
        judge.groups.add(group)

        form = UserProfileForm(instance=judge)
        self.assertIn('judge_type', form.fields)

    def test_show_judge_type_override(self):
        User = get_user_model()
        participant = User.objects.create_user(
            email='participant@example.com',
            password='pass1234',
            first_name='Hack',
            last_name='Er',
            email_verified=True,
        )

        form = UserProfileForm(instance=participant, show_judge_type=True)
        self.assertIn('judge_type', form.fields)
