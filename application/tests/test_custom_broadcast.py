import os
import tempfile

from django.core.mail import EmailMultiAlternatives
from django.test import SimpleTestCase, override_settings

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

    def test_attachment_notice_rendered_with_description_and_name(self):
        attachment = {'filename': 'access-pass.png', 'mimetype': 'image/png', 'content': b'data'}
        email = Email(
            'custom_broadcast',
            {
                'subject': 'Hi',
                'message': 'Body',
                'include_discord': False,
                'attachment_description': 'Access pass – show at check-in',
                'attachment_name': 'access-pass.png',
            },
            to='test@example.com',
            attachments=[attachment],
        )
        self.assertIn('Access pass – show at check-in', email.html_message)
        self.assertIn('access-pass.png', email.html_message)
        self.assertIn('Access pass – show at check-in', email.plain_text)
        self.assertEqual(email.attachments[0]['filename'], 'access-pass.png')

    def test_attachment_notice_omitted_when_not_provided(self):
        email = Email(
            'custom_broadcast',
            {
                'subject': 'Hi',
                'message': 'Body',
                'include_discord': False,
            },
            to='test@example.com',
        )
        self.assertNotIn('Attachment', email.html_message)

    @override_settings(DEBUG=False)
    def test_attachment_included_when_path_provided(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b'broadcast-pass')
            tmp_path = tmp.name
        try:
            email = Email(
                'custom_broadcast',
                {
                    'subject': 'Hi',
                    'message': 'Body',
                    'include_discord': False,
                },
                to='test@example.com',
                attachments=[{'filename': 'pass.png', 'mimetype': 'image/png', 'path': tmp_path}],
            )
            message = email.send(immediate=False)
            self.assertIsInstance(message, EmailMultiAlternatives)
            self.assertEqual(len(message.attachments), 1)
            attached_name, attached_content, attached_mime = message.attachments[0]
            self.assertTrue(attached_name)
            self.assertEqual(attached_content, b'broadcast-pass')
            self.assertEqual(attached_mime, 'image/png')
        finally:
            os.unlink(tmp_path)
