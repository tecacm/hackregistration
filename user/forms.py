import re

from captcha.fields import ReCaptchaField
from captcha import widgets as captcha_widgets
from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.core.validators import RegexValidator

from app.mixins import BootstrapFormMixin
from app.utils import get_theme, is_instance_on_db
from user.models import User
from judging.models import JudgeInviteCode
from user.choices import LEVELS_OF_STUDY, JUDGE_TYPE_CHOICES
from django.utils.translation import gettext_lazy as _


class RecaptchaForm(forms.Form):
    @classmethod
    def active(cls):
        return getattr(settings, 'RECAPTCHA_PUBLIC_KEY', False) and getattr(settings, 'RECAPTCHA_PRIVATE_KEY', False)

    def __init__(self, *args, **kwargs):
        request = kwargs.pop('request', None)
        widget_setting = getattr(settings, 'RECAPTCHA_WIDGET', 'ReCaptchaV2Checkbox')
        widget_class = getattr(captcha_widgets, widget_setting, captcha_widgets.ReCaptchaV2Checkbox)
        if widget_class == captcha_widgets.ReCaptchaBase or not issubclass(widget_class, captcha_widgets.ReCaptchaBase):
            widget_class = captcha_widgets.ReCaptchaV2Checkbox
        theme = get_theme(request) if request is not None else 'light'
        self.base_fields['captcha'] = ReCaptchaField(
            widget=widget_class(attrs={'data-theme': theme}),
            error_messages={'required': _('You must pass the reCAPTCHA challenge!')})
        super().__init__(*args, **kwargs)

    captcha = ReCaptchaField(
        widget=captcha_widgets.ReCaptchaV2Checkbox(),
        error_messages={'required': _('You must pass the reCAPTCHA challenge!')}
    )


class LoginForm(BootstrapFormMixin, forms.Form):
    bootstrap_field_info = {'': {'fields': [{'name': 'email', 'space': 12}, {'name': 'password', 'space': 12}]}}

    email = forms.EmailField(label=_('Email'), max_length=100)
    password = forms.CharField(widget=forms.PasswordInput, label=_('Password'), max_length=128)

    def clean_email(self):
        email = self.cleaned_data.get('email')
        return email.lower()

    def reset_status_fields(self):
        self.add_error('email', '')
        self.add_error('password', '')


class UserCreationForm(BootstrapFormMixin, forms.ModelForm):
    """A form for creating new users. Includes all the required
    fields, plus a repeated password."""

    bootstrap_field_info = {'': {'fields': [{'name': 'first_name', 'space': 6}, {'name': 'last_name', 'space': 6},
                                            {'name': 'email', 'space': 12}, {'name': 'password1', 'space': 12},
                                            {'name': 'password2', 'space': 12}]}}

    password1 = forms.CharField(label=_('Password'), widget=forms.PasswordInput, max_length=128)
    password2 = forms.CharField(label=_('Confirm your password'), widget=forms.PasswordInput, max_length=128,
                                help_text=password_validation.password_validators_help_text_html())

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')

    def clean_password2(self):
        # Check that the two password entries match
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError(_("Passwords don't match"))
        return password2

    def save(self, commit=True):
        # Save the provided password in hashed format
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        regex_organizer_email = getattr(settings, 'REGEX_HACKATHON_ORGANIZER_EMAIL', None)
        organizer_emails = getattr(settings, 'HACKATHON_ORGANIZER_EMAILS', [])
        if commit:
            user.save()
            if regex_organizer_email and re.match(regex_organizer_email, user.email) or user.email in organizer_emails:
                user.set_organizer()
        return user


class RegistrationForm(UserCreationForm):
    bootstrap_field_info = {'': {'fields': [{'name': 'first_name', 'space': 6}, {'name': 'last_name', 'space': 6},
                                            {'name': 'email', 'space': 12}, {'name': 'password1', 'space': 12},
                                            {'name': 'password2', 'space': 12},
                                            {'name': 'terms_and_conditions', 'space': 12},
                                            {'name': 'email_subscribe', 'space': 12}]}}

    terms_and_conditions = forms.BooleanField(
        label=mark_safe(_('I\'ve read, understand and accept the <a href="https://github.com/MLH/mlh-policies/blob/main/code-of-conduct.md" target="_blank">MLH Code of Conduct</a>.')))

    def clean_password2(self):
        password2 = super().clean_password2()
        password_validation.validate_password(password2)
        return password2

    def clean_terms_and_conditions(self):
        cc = self.cleaned_data.get('terms_and_conditions', False)
        # Check that if it's the first submission hackers checks terms and conditions checkbox
        # self.instance.pk is None if there's no Application existing before
        # https://stackoverflow.com/questions/9704067/test-if-django-modelform-has-instance
        if not cc and not self.instance.pk:
            raise forms.ValidationError(_(
                "In order to apply and attend you have to accept the MLH Code of Conduct."
            ))
        return cc

    class Meta(UserCreationForm.Meta):
        fields = ('first_name', 'last_name', 'email', 'password1', 'password2', 'email_subscribe')
        labels = {
            'email_subscribe': _('Subscribe to our mailing list to receive information about our next events.')
        }


class JudgeRegistrationForm(RegistrationForm):
    bootstrap_field_info = {'': {'fields': [
        {'name': 'first_name', 'space': 6},
        {'name': 'last_name', 'space': 6},
        {'name': 'email', 'space': 12},
        {'name': 'judge_type', 'space': 12},
        {'name': 'password1', 'space': 12},
        {'name': 'password2', 'space': 12},
        {'name': 'invite_code', 'space': 12},
        {'name': 'terms_and_conditions', 'space': 12},
    ]}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.invite_code_entry = None

    judge_type = forms.ChoiceField(
        choices=JUDGE_TYPE_CHOICES,
        required=True,
        label=_('What type of judge are you?'),
        help_text=_('We use this to tailor project assignments and communications.'),
    )
    invite_code = forms.CharField(
        label=_('Invite code'),
        max_length=128,
        help_text=_('Enter the invite code from your judge onboarding email.'),
    )
    terms_and_conditions = forms.BooleanField(
        label=_('I agree to uphold the HackMTY judging guidelines and Code of Conduct.'),
        help_text=_('You must agree before gaining access to the judging tools.'),
    )

    class Meta(RegistrationForm.Meta):
        fields = ('first_name', 'last_name', 'email', 'judge_type', 'password1', 'password2')
        labels = {}

    def clean_invite_code(self):
        code = (self.cleaned_data.get('invite_code') or '').strip()
        if not code:
            raise forms.ValidationError(_('Please provide your invite code.'))
        db_code = JudgeInviteCode.find_active(code)
        if db_code:
            if db_code.is_exhausted:
                raise forms.ValidationError(_('That invite code has already been used the maximum number of times.'))
            self.invite_code_entry = db_code
            return code
        fallback_codes = [value.lower() for value in getattr(settings, 'JUDGE_SIGNUP_CODES', []) if value]
        if fallback_codes:
            if code.lower() not in fallback_codes:
                raise forms.ValidationError(_('That invite code is not valid. Double-check your email or reach out to the organizers.'))
            return code
        if JudgeInviteCode.active().exists():
            raise forms.ValidationError(_('That invite code is not valid. Double-check your email or reach out to the organizers.'))
        raise forms.ValidationError(_('Judge registration is currently closed. Please contact the organizing team.'))

    def save(self, commit=True):
        with transaction.atomic():
            user = super().save(commit=commit)
            judge_type = self.cleaned_data.get('judge_type', '')
            if judge_type is not None:
                if commit:
                    if user.judge_type != judge_type:
                        user.judge_type = judge_type
                        user.save(update_fields=['judge_type'])
                else:
                    user.judge_type = judge_type
            if commit and self.invite_code_entry:
                try:
                    self.invite_code_entry.mark_used()
                except ValidationError as exc:
                    raise forms.ValidationError({'invite_code': exc.messages}) from exc
        return user


class UserChangeForm(forms.ModelForm):
    """A form for updating users. Includes all the fields on
    the user, but replaces the password field with admin's
    disabled password hash display field.
    """
    password = ReadOnlyPasswordHashField()
    # user_permissions = forms.ModelMultipleChoiceField(queryset=Permission.objects.filter(
    #     content_type__app_label='application'))

    class Meta:
        model = User
        fields = '__all__'


class UserProfileForm(BootstrapFormMixin, forms.ModelForm):
    bootstrap_field_info = {_('Personal Info'): {'fields': [
        {'name': 'first_name', 'space': 6}, {'name': 'last_name', 'space': 6}, {'name': 'email', 'space': 6},
        {'name': 'phone_number', 'space': 6}, {'name': 'tshirt_size', 'space': 4}, {'name': 'diet', 'space': 4},
        {'name': 'other_diet', 'space': 4, 'visible': {'diet': User.DIET_OTHER}}, {'name': 'birth_date', 'space': 4},
        {'name': 'gender', 'space': 4}, {'name': 'other_gender', 'space': 4, 'visible': {'gender': User.GENDER_OTHER}},
        {'name': 'judge_type', 'space': 4},
    ],
        'description': _('Hey there, before we begin, we would like to know a little more about you.')}, }

    # Capture age as an integer but map it internally to a synthetic birth_date so existing
    # age calculations & statistics (which rely on birth_date) still work.
    # We generate a birth_date with today's month/day minus the provided years so age property matches input.
    birth_date = forms.IntegerField(
        label=_('Age (as of dates of %(hackathon)s)') % {'hackathon': getattr(settings, 'HACKATHON_NAME', '')},
        required=False,
        min_value=10,
        max_value=100,
        help_text=_('Enter your age in years. We will not store your exact birth date, only an inferred year.'),
        error_messages={
            'required': _('Please tell us your age.'),
            'invalid': _('Please enter a valid age.'),
            'min_value': _('Age must be at least %(limit_value)s.'),
            'max_value': _('Age can be at most %(limit_value)s.'),
        }
    )

    # Override model field to enforce required at form level
    phone_number = forms.CharField(
        validators=[RegexValidator(regex=r'^\+?1?\d{9,15}$')],
        required=True,
        max_length=20,
        label=_('Phone number'),
        help_text=_('Phone number must be entered in the format: +#########. Up to 15 digits allowed.'),
        widget=forms.TextInput(attrs={'placeholder': '+#########'})
    )

    level_of_study = forms.ChoiceField(choices=LEVELS_OF_STUDY, required=True, label=_('Level of Study'))
    judge_type = forms.ChoiceField(
        choices=[('', _('Select judge type'))] + list(JUDGE_TYPE_CHOICES),
        required=False,
        label=_('Judge type'),
        help_text=_('Let organisers know the perspective you bring when judging.'),
    )

    def __init__(self, *args, show_judge_type=None, **kwargs):
        instance = kwargs.get('instance')
        if show_judge_type is None:
            if instance is not None:
                show_judge_type = instance.groups.filter(name='Judge').exists()
            else:
                show_judge_type = False
        self.show_judge_type = bool(show_judge_type)
        super().__init__(*args, **kwargs)
        if not self.show_judge_type:
            self.fields.pop('judge_type', None)
        instance = getattr(self, 'instance', None)

        birth_field = self.fields['birth_date']
        require_age = not is_instance_on_db(instance) or not getattr(instance, 'birth_date', None)
        if require_age:
            birth_field.required = True
            birth_field.widget.attrs['required'] = 'required'
        else:
            birth_field.required = False
            birth_field.widget.attrs.pop('required', None)

        if is_instance_on_db(instance):  # instance in DB
            email_field = self.fields.get('email')
            email_field.widget.attrs['readonly'] = True
            email_field.help_text = _('This field cannot be modified')
            # Populate age integer from stored synthetic birth_date
            if instance and instance.birth_date:
                self.initial['birth_date'] = instance.age

    def get_bootstrap_field_info(self):
        info = super().get_bootstrap_field_info()
        if not getattr(self, 'show_judge_type', False):
            for section in info.values():
                section['fields'] = [field for field in section.get('fields', []) if field.get('name') != 'judge_type']
        instance = getattr(self, 'instance', None)
        if not is_instance_on_db(instance):  # instance not in DB
            fields = info[_('Personal Info')]['fields']
            result = []
            for field in fields:
                if field['name'] not in self.Meta.fields_only_public:
                    if field['space'] == 4:
                        field['space'] = 6
                else:
                    field['space'] = 0
                result.append(field)
            info[_('Personal Info')]['fields'] = result
        return info

    def clean_email(self):
        instance = getattr(self, 'instance', None)
        if is_instance_on_db(instance):  # instance in DB
            return self.instance.email
        return self.cleaned_data.get('email')

    def clean_birth_date(self):
        age = self.cleaned_data.get('birth_date')
        if age in (None, ''):
            if self.fields['birth_date'].required:
                raise forms.ValidationError(_('Please tell us your age.'))
            return None
        # Convert supplied age to a deterministic birth_date so age calculations remain stable.
        today = timezone.now().date()
        try:
            age_int = int(age)
        except (TypeError, ValueError):
            raise forms.ValidationError(_('Please enter a valid age.'))
        if age_int < 10 or age_int > 100:
            raise forms.ValidationError(_('Age must be between 10 and 100.'))
        synthetic = today.replace(year=today.year - age_int)
        return synthetic

    class Meta:
        model = User
        fields = ['first_name', 'email', 'last_name', 'phone_number', 'diet', 'other_diet', 'gender',
                  'other_gender', 'birth_date', 'level_of_study', 'judge_type', 'tshirt_size']
        fields_only_public = ['birth_date', 'tshirt_size']
        help_texts = {
            'gender': _('This is for demographic purposes. You can skip this question if you want.'),
            'other_diet': _('Please fill here in your dietary requirements. '
                            'We want to make sure we have food for you!'),
        }
        labels = {
            'gender': _('What gender do you identify as?'),
            'other_gender': _('Self-describe'),
            'tshirt_size': _('What\'s your t-shirt size?'),
            'diet': _('Dietary requirements'),
            'phone_number': _('Phone number'),
            'level_of_study': _('Level of Study'),
            'judge_type': _('Judge type'),
        }


class ForgotPasswordForm(BootstrapFormMixin, forms.Form):
    bootstrap_field_info = {'': {'fields': [{'name': 'email', 'space': 12}]}}

    email = forms.EmailField(label=_('Email'), max_length=100)


class SetPasswordForm(BootstrapFormMixin, forms.ModelForm):
    """
    A form that lets a user change set their password without entering the old
    password
    """

    bootstrap_field_info = {'': {'fields': [{'name': 'password', 'space': 12},
                                            {'name': 'new_password2', 'space': 12}]}}

    password = forms.CharField(
        label=_("New password"),
        widget=forms.PasswordInput,
        strip=False,
    )
    new_password2 = forms.CharField(
        label=_("Confirm your new password"),
        strip=False,
        widget=forms.PasswordInput,
        help_text=password_validation.password_validators_help_text_html(),
    )

    def clean_new_password2(self):
        password1 = self.cleaned_data.get('password')
        password2 = self.cleaned_data.get('new_password2')
        if password1 and password2:
            if password1 != password2:
                raise forms.ValidationError(_("The passwords do not match."))
        password_validation.validate_password(password2, self.instance)
        return password2

    def save(self, commit=True):
        password = self.cleaned_data["password"]
        self.instance.set_password(password)
        if commit:
            self.instance.save()
        return self.instance

    class Meta:
        model = User
        fields = ['password', 'new_password2']
