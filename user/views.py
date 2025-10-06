import json
import logging

from anymail.exceptions import AnymailError
from axes.handlers.proxy import AxesProxyHandler
from axes.helpers import get_client_ip_address, get_cool_off
from axes.models import AccessAttempt
from axes.utils import reset_request
from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth.models import Group
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.shortcuts import redirect
from django.urls import reverse, resolve, reverse_lazy, NoReverseMatch
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from django.utils.translation import gettext as _
from django.core.exceptions import ValidationError
from django.db import transaction

from app.mixins import TabsViewMixin
from user import emails
from user.forms import (
    LoginForm,
    UserProfileForm,
    ForgotPasswordForm,
    SetPasswordForm,
    RegistrationForm,
    RecaptchaForm,
    JudgeRegistrationForm,
)
from user.mixins import LoginRequiredMixin, EmailNotVerifiedMixin
from user.models import User
from user.tokens import AccountActivationTokenGenerator
from judging.models import JudgeInviteCode
from application.models import Application, ApplicationTypeConfig, Edition


class AuthTemplateViews(TabsViewMixin, TemplateView):
    template_name = 'auth.html'
    names = {
        'login': 'log in',
        'register': 'register',
    }
    forms = {
        'login': LoginForm,
        'register': RegistrationForm,
    }

    def get_current_tabs(self, **kwargs):
        return [('Log in', reverse('login')), ('Register', reverse('register'))]

    def redirect_successful(self):
        next_url = self.request.GET.get('next')
        if next_url:
            if next_url.startswith('/'):
                return redirect(next_url)
            return redirect(reverse('home'))

        user = getattr(self.request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            try:
                if user.groups.filter(name='Judge').exists():
                    try:
                        return redirect(reverse('judging:dashboard'))
                    except NoReverseMatch:
                        return redirect(reverse('event:judges_guide'))
            except Exception:
                # Defensive: if group lookup fails, fall back to the home page
                pass

        return redirect(reverse('home'))

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return self.redirect_successful()
        return super().get(request, *args, **kwargs)

    @property
    def get_url_name(self):
        return resolve(self.request.path_info).url_name

    def get_form_class(self):
        return self.forms.get(self.get_url_name)

    def get_form(self):
        form_class = self.get_form_class()
        return form_class()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'form': self.get_form(), 'auth': self.names.get(self.get_url_name, 'register')})
        if getattr(settings, 'RECAPTCHA_%s' % self.get_url_name.upper(), False) and RecaptchaForm.active():
            context.update({'recaptcha_form': RecaptchaForm(request=self.request)})
        return context

    def forms_are_valid(self, form, context):
        if getattr(settings, 'RECAPTCHA_%s' % self.get_url_name.upper(), False) and RecaptchaForm.active():
            recaptcha_form = RecaptchaForm(self.request.POST, request=self.request)
            if not recaptcha_form.is_valid():
                context.update({'recaptcha_form': recaptcha_form})
                return False
        return form.is_valid()


class Login(AuthTemplateViews):
    def add_axes_context(self, context):
        if not AxesProxyHandler.is_allowed(self.request):
            ip_address = get_client_ip_address(self.request)
            attempt = AccessAttempt.objects\
                .filter(ip_address=ip_address, failures_since_start__gte=getattr(settings, 'AXES_FAILURE_LIMIT'))\
                .first()
            if attempt is not None:
                time_left = (attempt.attempt_time + get_cool_off()) - timezone.now()
                minutes_left = int((time_left.total_seconds() + 59) // 60)
            else:
                minutes_left = 5
            axes_error_message = _('Too many login attempts. Please try again in %s minutes.') % minutes_left
            context.update({'blocked_message': axes_error_message})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self.add_axes_context(context)
        return context

    def post(self, request, **kwargs):
        form = LoginForm(request.POST)
        context = self.get_context_data(**kwargs)
        if self.forms_are_valid(form, context):
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            user = auth.authenticate(email=email, password=password, request=request)
            if user and user.is_active:
                auth.login(request, user)
                reset_request(request)
                messages.success(request, _('Successfully logged in!'))
                return self.redirect_successful()
            elif getattr(request, 'axes_locked_out', False):
                return redirect(reverse('login'))
            else:
                form.add_error(None, _('Incorrect username or password. Please try again.'))
        form.reset_status_fields()
        context.update({'form': form})
        return self.render_to_response(context)


class Register(Login):
    form_class = RegistrationForm

    def get_form_class(self):
        return self.form_class

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'form': self.get_form_class()(), 'auth': 'register'})
        context.pop("blocked_message", None)
        return context

    def after_user_created(self, user):
        return user

    def should_send_verification_email(self):
        return True

    def get_success_message(self):
        return _('Successfully registered!')

    def post(self, request, **kwargs):
        context = self.get_context_data(**kwargs)
        form_class = self.get_form_class()
        form = form_class(request.POST)
        recaptcha = RecaptchaForm(request.POST, request=request)
        if self.forms_are_valid(form, context):
            try:
                with transaction.atomic():
                    user = form.save()
            except ValidationError as exc:
                error_dict = exc.message_dict if hasattr(exc, 'message_dict') else {'__all__': exc.messages}
                for field, field_messages in error_dict.items():
                    target_field = field if field in form.fields else None
                    for message in field_messages:
                        form.add_error(target_field, message)
                context.update({'form': form, 'recaptcha_form': recaptcha})
                return self.render_to_response(context)
            self.after_user_created(user)
            auth.login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            if self.should_send_verification_email():
                try:
                    emails.send_verification_email(request=request, user=user)
                    messages.success(request, self.get_success_message())
                except AnymailError as e:
                    logging.getLogger(__name__).warning("Verification email send failed during registration: %s", e)
                    messages.warning(
                        request,
                        _("Registered, but we couldn't send the verification email. Please confirm your email address is correct and try again."),
                    )
            else:
                messages.success(request, self.get_success_message())
            return self.redirect_successful()
        context.update({'form': form, 'recaptcha_form': recaptcha})
        return self.render_to_response(context)


class Logout(View):
    def get(self, request, **kwargs):
        auth.logout(request)
        messages.success(request, _('Successfully logged out!'))
        return self.redirect_successful()

    def redirect_successful(self):
        next_ = self.request.GET.get('next', reverse('login'))
        if next_[0] != '/':
            next_ = reverse('login')
        return redirect(next_)


class JudgeRegister(Register):
    template_name = 'judges/signup.html'
    form_class = JudgeRegistrationForm

    def get_form(self):
        initial = {}
        code = self.request.GET.get('code')
        if code:
            initial['invite_code'] = code
        return self.get_form_class()(initial=initial)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'auth': 'join as judge',
            'tabs': [],
            'headline': _('Welcome judges!'),
            'subheadline': _('Create your account to access the scoring tools and event briefings.'),
            'judging_dashboard_url': reverse('judging:dashboard'),
            'judging_launch_url': reverse('judging:launch'),
            'judges_guide_url': reverse('event:judges_guide'),
            'submit_label': _('Join as judge'),
              'invite_required': JudgeInviteCode.active().exists() or bool(getattr(settings, 'JUDGE_SIGNUP_CODES', [])),
        })
        return context

    def after_user_created(self, user):
        group, _ = Group.objects.get_or_create(name='Judge')
        user.groups.add(group)
        if not getattr(user, 'email_verified', False):
            user.email_verified = True
            user.save(update_fields=['email_verified'])
        self.ensure_judge_application(user)
        return user

    def ensure_judge_application(self, user):
        edition = Edition.objects.order_by('-order').first()
        if edition is None:
            return

        defaults = {
            'start_application_date': timezone.now(),
            'end_application_date': timezone.now() + timezone.timedelta(days=365),
            'vote': False,
            'dubious': False,
            'auto_confirm': True,
            'compatible_with_others': True,
            'create_user': False,
            'hidden': True,
        }
        judge_type_config, _ = ApplicationTypeConfig.objects.get_or_create(name='Judge', defaults=defaults)

        now = timezone.now()
        application, _ = Application.objects.get_or_create(
            user=user,
            type=judge_type_config,
            edition=edition,
            defaults={
                'status': Application.STATUS_CONFIRMED,
                'submission_date': now,
                'last_modified': now,
                'status_update_date': now,
            },
        )

        judge_type_value = getattr(user, 'judge_type', '')
        if judge_type_value:
            try:
                data = json.loads(application.data) if application.data else {}
            except json.JSONDecodeError:
                data = {}
            if data.get('judge_type') != judge_type_value:
                data['judge_type'] = judge_type_value
                application.data = json.dumps(data)
                application.save(update_fields=['data'])

    def should_send_verification_email(self):
        return False

    def get_success_message(self):
        return _('Welcome to the judging team! You are ready to score projects.')

    def redirect_successful(self):
        return redirect(reverse('judging:dashboard'))


class Profile(LoginRequiredMixin, TemplateView):
    template_name = 'profile.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'form': UserProfileForm(instance=self.request.user)})
        return context

    def post(self, request, **kwargs):
        delete = request.POST.get('delete', '')
        if delete != '' and delete == request.user.email:
            request.user.set_unknown()
            request.user.save()
            auth.logout(request)
            messages.success(request, _('User deleted!'))
            return redirect('login')
        form = UserProfileForm(instance=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Profile changed!'))
            return redirect('profile')
        context = self.get_context_data(**kwargs)
        context.update({'form': form})
        return self.render_to_response(context)


class NeedsVerification(EmailNotVerifiedMixin, TemplateView):
    template_name = 'needs_verification.html'

    def post(self, request, **kwargs):
        sent = emails.send_verification_email(request=request, user=request.user)
        if sent:
            messages.success(request, "Verification email successfully sent")
            return redirect('home')
        # Don’t error out if email sending failed; inform the user and keep them on the page
        messages.error(request, "We couldn't send the verification email. Please check your email address or try again later.")
        return redirect('needs_verification')


class VerifyEmail(View):
    def get(self, request, **kwargs):
        try:
            uid = User.decode_encoded_pk(kwargs.get('uid'))
            user = User.objects.get(pk=uid)
            if request.user.is_authenticated and request.user != user:
                messages.warning(request, _("Trying to verify wrong user. Log out please!"))
                return redirect('home')
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            messages.warning(request, _("This user no longer exists. Please sign up again!"))
            return redirect('register')

        if AccountActivationTokenGenerator().check_token(user=user, token=kwargs.get('token')):
            # Mark verified
            user.email_verified = True
            user.save(update_fields=["email_verified", "modified" if hasattr(user, 'modified') else "email_verified"])
            # Log the user in (ensures session for immediate access to application pages)
            auth.login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, _("Email verified!"))
            # Send directly to application home (role selection)
            return redirect(reverse_lazy('apply_home'))

        messages.error(request, _("Email verification link is invalid or has expired. Log in to request a new one."))
        return redirect('needs_verification')


class ForgotPassword(TemplateView):
    template_name = 'forgot_password.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'form': ForgotPasswordForm(), 'success': self.request.GET.get('success', 'false') == 'true'})
        return context

    def post(self, request, **kwargs):
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            try:
                email = form.cleaned_data.get('email')
                user = User.objects.get(email=email)
                try:
                    emails.send_password_reset_email(request=request, user=user)
                except AnymailError as e:
                    logging.getLogger(__name__).warning("Password reset email send failed: %s", e)
            except User.DoesNotExist:
                pass
            messages.success(request, 'Email sent if it exists!')
            return redirect(reverse('forgot_password') + '?success=true')
        context = self.get_context_data(**kwargs)
        context.update({'form': form})
        return self.render_to_response(context)


class ChangePassword(TemplateView):
    template_name = 'password_reset.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = None
        try:
            uid = User.decode_encoded_pk(self.kwargs.get('uid'))
            user = User.objects.get(pk=uid)
            form = SetPasswordForm(instance=user)
            if PasswordResetTokenGenerator().check_token(user, self.kwargs.get('token')):
                context.update({'user': user})
            else:
                context.update({'error': _('Invalid link')})
        except User.DoesNotExist:
            context.update({'error': _('Invalid link')})
        context.update({'form': form, 'new': self.request.GET.get('new', None)})
        return context

    def post(self, request, **kwargs):
        context = self.get_context_data()
        if context.get('user', None) is not None:
            form = SetPasswordForm(request.POST, instance=context['user'])
            if form.is_valid():
                form.save()
                context.update({'success': True})
            else:
                context.update({'form': form})
        return self.render_to_response(context)
