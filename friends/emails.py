from typing import Iterable

from django.conf import settings

from app.emails import Email


def send_track_assigned_email(team_code: str, track_label: str, recipients: Iterable[str]) -> int:
    recipient_list = sorted({email for email in recipients if email})
    if not recipient_list:
        return 0
    contact_email = getattr(settings, 'HACKATHON_CONTACT_EMAIL', 'hello@hackmty.com')
    context = {
        'code': team_code,
        'track': track_label,
        'contact_email': contact_email,
    }
    return Email(name='track_assigned', context=context, to=recipient_list).send()


def send_track_reassigned_email(team_code: str, old_track_label: str, new_track_label: str, recipients: Iterable[str]) -> int:
    recipient_list = sorted({email for email in recipients if email})
    if not recipient_list:
        return 0
    contact_email = getattr(settings, 'HACKATHON_CONTACT_EMAIL', 'hello@hackmty.com')
    context = {
        'code': team_code,
        'old_track': old_track_label,
        'new_track': new_track_label,
        'contact_email': contact_email,
    }
    return Email(name='track_reassigned', context=context, to=recipient_list).send()
