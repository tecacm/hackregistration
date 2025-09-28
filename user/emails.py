from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.urls import reverse

import logging
from anymail.exceptions import AnymailError
from app.emails import Email
from user.tokens import AccountActivationTokenGenerator

logger = logging.getLogger(__name__)

def send_verification_email(request, user) -> bool:
    # Guard against invalid or empty recipient addresses to avoid AnymailRecipientsRefused
    try:
        if not getattr(user, 'email', None):
            return False
        validate_email(user.email)
    except ValidationError:
        return False
    token = AccountActivationTokenGenerator().make_token(user)
    uuid = user.get_encoded_pk()
    url = request.build_absolute_uri(reverse('verify_email', kwargs={'uid': uuid, 'token': token}))
    context = {
        'user': user,
        'url': url,
    }
    try:
        result = Email(name='verify_email', context=context, to=user.email, request=request).send()
        # Django's EmailMessage.send returns number of successfully delivered messages
        return bool(result)
    except AnymailError as e:
        # Don’t crash user flows if the ESP rejects an address; surface as a user-friendly message instead
        logger.warning("Verification email send failed for %s: %s", user.email, e)
        return False


def send_password_reset_email(request, user) -> bool:
    # Validate email before attempting send
    try:
        if not getattr(user, 'email', None):
            return False
        validate_email(user.email)
    except ValidationError:
        return False
    token = PasswordResetTokenGenerator().make_token(user)
    uuid = user.get_encoded_pk()
    url = request.build_absolute_uri(reverse('password_reset', kwargs={'uid': uuid, 'token': token}))
    context = {
        'user': user,
        'url': url,
    }
    try:
        result = Email(name='password_reset', context=context, to=user.email, request=request).send()
        return bool(result)
    except AnymailError as e:
        logger.warning("Password reset email send failed for %s: %s", user.email, e)
        return False
    
