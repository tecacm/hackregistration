from django.test import SimpleTestCase

from app.emails import Email


class CustomBroadcastEmailTests(SimpleTestCase):
    def test_discord_block_included_when_flag_true(self):
        email = Email(
            'custom_broadcast',
            {'subject': 'Hello', 'message': 'Body', 'include_discord': True},
            to='test@example.com',
        )
        self.assertIn('Join our Discord', email.html_message)
        self.assertIn('Join our Discord', email.plain_text)

    def test_discord_block_omitted_when_flag_false(self):
        email = Email(
            'custom_broadcast',
            {'subject': 'Hello', 'message': 'Body', 'include_discord': False},
            to='test@example.com',
        )
        self.assertNotIn('Join our Discord', email.html_message)
        self.assertNotIn('Join our Discord', email.plain_text)
