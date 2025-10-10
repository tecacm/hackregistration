from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from application.models import Application, ApplicationTypeConfig, Edition
from friends.matchmaking import MatchmakingService
from friends.models import FriendsCode, FriendsMergePoolEntry, FriendsMembershipLog


class MatchmakingTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.delete(Edition.get_default_edition.__qualname__)
        self.edition = Edition.objects.create(name='Test Edition', order=99)
        self.app_type = ApplicationTypeConfig.objects.create(name='Hacker')

    def _make_user(self, email):
        User = get_user_model()
        return User.objects.create_user(email=email, password='test12345')

    def _create_pending_application(self, user):
        return Application.objects.create(
            user=user,
            type=self.app_type,
            edition=self.edition,
            status=Application.STATUS_PENDING,
        )

    def test_opt_in_creates_pool_entry(self):
        user_a = self._make_user('alpha@example.com')
        user_b = self._make_user('bravo@example.com')
        self._create_pending_application(user_a)
        self._create_pending_application(user_b)

        team_code = FriendsCode.objects.create(user=user_a).code
        FriendsCode.objects.create(user=user_b, code=team_code)

        token = MatchmakingService.generate_opt_in_token(user_a, self.edition, team_code)
        response = self.client.get(reverse('friends_merge_opt_in', args=[token]))
        self.assertEqual(response.status_code, 200)
        entry = FriendsMergePoolEntry.objects.get(team_code=team_code)
        self.assertEqual(entry.status, FriendsMergePoolEntry.STATUS_PENDING)
        self.assertTrue(FriendsCode.objects.filter(code=team_code, seeking_merge=True).exists())

    @mock.patch('friends.matchmaking.Email.send', return_value=1)
    def test_matching_merges_two_partial_teams(self, mocked_email):
        team_one_users = [self._make_user(f'team1_{i}@example.com') for i in range(2)]
        team_two_users = [self._make_user(f'team2_{i}@example.com') for i in range(2)]
        for user in team_one_users + team_two_users:
            self._create_pending_application(user)

        team_one_code = FriendsCode.objects.create(user=team_one_users[0]).code
        FriendsCode.objects.create(user=team_one_users[1], code=team_one_code)
        team_two_code = FriendsCode.objects.create(user=team_two_users[0]).code
        FriendsCode.objects.create(user=team_two_users[1], code=team_two_code)

        for user, code in ((team_one_users[0], team_one_code), (team_two_users[0], team_two_code)):
            token = MatchmakingService.generate_opt_in_token(user, self.edition, code)
            MatchmakingService.process_opt_in_token(token)

        results = MatchmakingService.run_matching(self.edition)
        self.assertEqual(len(results), 1)
        host_code = results[0].team_code
        self.assertEqual(
            set(FriendsCode.objects.filter(code=host_code).values_list('user__email', flat=True)),
            {user.email for user in team_one_users + team_two_users},
        )
        entries = FriendsMergePoolEntry.objects.filter(team_code__in=[team_one_code, team_two_code])
        self.assertTrue(all(entry.status == FriendsMergePoolEntry.STATUS_MATCHED for entry in entries))
        mocked_email.assert_called_once()


class MatchmakingAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.delete(Edition.get_default_edition.__qualname__)
        self.edition = Edition.objects.create(name='Admin Edition', order=100)
        self.app_type = ApplicationTypeConfig.objects.create(name='Hacker')
        self.admin_user = get_user_model().objects.create_superuser('admin@example.com', 'password123')
        self.client.force_login(self.admin_user, backend='django.contrib.auth.backends.ModelBackend')

    def _make_user(self, email):
        User = get_user_model()
        return User.objects.create_user(email=email, password='test12345')

    def _create_pending_application(self, user):
        return Application.objects.create(
            user=user,
            type=self.app_type,
            edition=self.edition,
            status=Application.STATUS_PENDING,
        )

    def test_matchmaking_dashboard_accessible(self):
        response = self.client.get(
            reverse('admin:friends_friendsmergepoolentry_matchmaking'),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Send opt-in invitations')

    def test_invite_preview_via_admin(self):
        user = self._make_user('dryrun@example.com')
        self._create_pending_application(user)

        response = self.client.post(
            reverse('admin:friends_friendsmergepoolentry_matchmaking'),
            {
                'invite-preview': '1',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Preview recipients')
        preview = response.context['invite_preview']
        self.assertIsNotNone(preview)
        self.assertEqual(preview['total_recipients'], 1)
        self.assertIn('dryrun@example.com', response.content.decode())
        self.assertIn('Hi', preview['sample_email']['html'])

    @mock.patch('friends.matchmaking.Email.send', return_value=1)
    def test_invite_send_via_admin(self, mocked_email):
        user = self._make_user('sendrun@example.com')
        self._create_pending_application(user)

        response = self.client.post(
            reverse('admin:friends_friendsmergepoolentry_matchmaking'),
            {
                'invite-send': '1',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(mocked_email.called)
        self.assertContains(response, 'invite(s) queued for delivery')

    @mock.patch('friends.matchmaking.Email.send', return_value=1)
    def test_run_matching_from_admin(self, mocked_email):
        team_one_users = [self._make_user(f'admin_team1_{i}@example.com') for i in range(2)]
        team_two_users = [self._make_user(f'admin_team2_{i}@example.com') for i in range(2)]
        for user in team_one_users + team_two_users:
            self._create_pending_application(user)

        team_one_code = FriendsCode.objects.create(user=team_one_users[0]).code
        FriendsCode.objects.create(user=team_one_users[1], code=team_one_code)
        team_two_code = FriendsCode.objects.create(user=team_two_users[0]).code
        FriendsCode.objects.create(user=team_two_users[1], code=team_two_code)

        for user, code in ((team_one_users[0], team_one_code), (team_two_users[0], team_two_code)):
            token = MatchmakingService.generate_opt_in_token(user, self.edition, code)
            MatchmakingService.process_opt_in_token(token)

        response = self.client.post(
            reverse('admin:friends_friendsmergepoolentry_matchmaking'),
            {
                'match-submit': '1',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Matching run merged')
        mocked_email.assert_called()


class TeamMembershipAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.delete(Edition.get_default_edition.__qualname__)
        self.edition = Edition.objects.create(name='Membership Edition', order=110)
        self.app_type = ApplicationTypeConfig.objects.create(name='Hacker')
        self.admin_user = get_user_model().objects.create_superuser('admin-membership@example.com', 'password123')
        self.client.force_login(self.admin_user, backend='django.contrib.auth.backends.ModelBackend')

    def _make_user(self, email):
        User = get_user_model()
        return User.objects.create_user(email=email, password='test12345')

    def _create_pending_application(self, user):
        return Application.objects.create(
            user=user,
            type=self.app_type,
            edition=self.edition,
            status=Application.STATUS_PENDING,
        )

    def test_add_member_to_existing_team(self):
        captain = self._make_user('captain@example.com')
        teammate = self._make_user('teammate@example.com')
        self._create_pending_application(captain)
        self._create_pending_application(teammate)
        team_code = FriendsCode.objects.create(user=captain).code

        response = self.client.post(
            reverse('admin:friends_friendscode_membership'),
            {
                'add-email': teammate.email,
                'add-team_code': team_code,
                'add-move_if_exists': 'on',
                'add-submit': '1',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(FriendsCode.objects.filter(user=teammate, code=team_code).exists())
        log = FriendsMembershipLog.objects.filter(affected_user=teammate).latest('timestamp')
        self.assertEqual(log.action, FriendsMembershipLog.ACTION_ADD)
        self.assertEqual(log.to_code, team_code)

    def test_move_member_creates_new_team(self):
        user = self._make_user('solo@example.com')
        self._create_pending_application(user)
        original_code = FriendsCode.objects.create(user=user).code

        response = self.client.post(
            reverse('admin:friends_friendscode_membership'),
            {
                'add-email': user.email,
                'add-move_if_exists': 'on',
                'add-submit': '1',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        new_code = FriendsCode.objects.get(user=user).code
        self.assertNotEqual(new_code, original_code)
        log = FriendsMembershipLog.objects.filter(affected_user=user).latest('timestamp')
        self.assertEqual(log.action, FriendsMembershipLog.ACTION_MOVE)
        self.assertEqual(log.from_code, original_code)
        self.assertEqual(log.to_code, new_code)

    def test_remove_member_clears_team(self):
        user = self._make_user('remove@example.com')
        self._create_pending_application(user)
        team_code = FriendsCode.objects.create(user=user).code

        response = self.client.post(
            reverse('admin:friends_friendscode_membership'),
            {
                'remove-email': user.email,
                'remove-confirm': 'on',
                'remove-submit': '1',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FriendsCode.objects.filter(user=user).exists())
        log = FriendsMembershipLog.objects.filter(affected_user=user).latest('timestamp')
        self.assertEqual(log.action, FriendsMembershipLog.ACTION_REMOVE)
        self.assertEqual(log.from_code, team_code)
