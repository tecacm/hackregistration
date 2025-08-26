from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from app.mixins import BootstrapFormMixin
from app.utils import is_instance_on_db
from application.models import Application


CURRENT_YEAR = timezone.now().year
# Include previous year so applicants who just graduated can still pick their (past) graduation year
YEARS = [(year, str(year)) for year in range(CURRENT_YEAR - 1, CURRENT_YEAR + 6)]
DEFAULT_YEAR = timezone.now().year + 1
EXTENSIONS = getattr(settings, 'SUPPORTED_RESUME_EXTENSIONS', None)

HACK_NAME = getattr(settings, 'HACKATHON_NAME')
EXTRA_NAME = [' 2016 Fall', ' 2016 Winter', ' 2017 Fall', '  2017 Winter', ' 2018', ' 2019', ' 2021', ' 2022']
PREVIOUS_HACKS = [(i, HACK_NAME + EXTRA_NAME[i]) for i in range(0, len(EXTRA_NAME))]
HACK_DAYS = [(x, x) for x in ['Friday', 'Saturday', 'Sunday']]
ENGLISH_LEVELS = [(x, x) for x in ['1', '2', '3', '4', '5']]


class ApplicationForm(BootstrapFormMixin, forms.ModelForm):

    diet_notice = forms.BooleanField(
        label=_('Authorize %s the use of my food allergies and intolerances data for the sole purpose of managing the catering service.') % getattr(settings, 'HACKATHON_ORG')
    )

    terms_and_conditions = forms.BooleanField(
        label=mark_safe(_('I\'ve read, understand and accept the <a href="https://github.com/MLH/mlh-policies/blob/main/code-of-conduct.md" target="_blank">MLH Code of Conduct</a>.'))
    )

    # MLH required/optional checkboxes (Code of Conduct acceptance kept as terms_and_conditions)
    mlh_data = forms.BooleanField(
        label=mark_safe(_('I authorize you to share my application/registration information with Major League Hacking for event administration, ranking, and MLH administration in-line with the <a href="https://github.com/MLH/mlh-policies/blob/main/privacy-policy.md" target="_blank">MLH Privacy Policy</a>. I further agree to the terms of both the <a href="https://github.com/MLH/mlh-policies/blob/main/contest-terms.md" target="_blank">MLH Contest Terms and Conditions</a> and the <a href="https://github.com/MLH/mlh-policies/blob/main/privacy-policy.md" target="_blank">MLH Privacy Policy</a>.')),
        required=True
    )
    mlh_emails = forms.BooleanField(
        label=_('I authorize MLH to send me occasional emails about relevant events, career opportunities, and community announcements.'),
        required=False
    )

    exclude_save = ['terms_and_conditions', 'diet_notice']

    def save(self, commit=True):
        model_fields = [field.name for field in self.Meta.model._meta.fields]
        extra_fields = [field for field in self.declared_fields if field not in model_fields and
                        field not in self.exclude_save]
        files_fields = getattr(self, 'files', {})
        extra_data = {field: data for field, data in self.cleaned_data.items()
                      if field in extra_fields and field not in files_fields.keys()}
        self.instance.form_data = extra_data
        instance = super().save(commit)
        if commit:
            self.save_files(instance=instance)
            # Sync level_of_study (form-only field) into related user profile if provided
            level = self.cleaned_data.get('level_of_study')
            if level and hasattr(instance, 'user') and hasattr(instance.user, 'level_of_study'):
                if instance.user.level_of_study != level:
                    instance.user.level_of_study = level
                    instance.user.save(update_fields=['level_of_study'])
        return instance

    def save_files(self, instance):
        files_fields = getattr(self, 'files', {})
        fs = FileSystemStorage()
        for field_name, file in files_fields.items():
            file_path = '%s/%s/%s/%s_%s.%s' % (instance.edition.name, instance.type.name, field_name,
                                               instance.get_full_name().replace(' ', '-'), instance.get_uuid,
                                               file.name.split('.')[-1])
            if fs.exists(file_path):
                fs.delete(file_path)
            fs.save(name=file_path, content=file)
            form_data = instance.form_data
            form_data[field_name] = {'type': 'file', 'path': file_path}
            instance.form_data = form_data
        if len(files_fields) > 0:
            instance.save()
        return files_fields.keys()

    def get_hidden_edit_fields(self):
        # Fields that should not be required when editing an existing application
        fields = self.exclude_save.copy()
        # Do not force MLH data consent again on edit (policy already given on apply)
        fields.extend(['mlh_data'])
        return fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.update(self.instance.form_data)
        instance = kwargs.get('instance', None)
        hidden_fields = self.get_hidden_edit_fields()
        if is_instance_on_db(instance):  # instance in DB
            for hidden_field in hidden_fields:
                self.fields.get(hidden_field).required = False

    def get_bootstrap_field_info(self):
        fields = super().get_bootstrap_field_info()
        instance = getattr(self, 'instance', None)
        if not is_instance_on_db(instance):  # instance not in DB
            policy_fields = self.get_policy_fields()
            fields.update({
                _('HackMTY Policies'): {
                    'fields': policy_fields,
                    'description': '<p style="color: margin-top: 1em;display: block;'
                                   'margin-bottom: 1em;line-height: 1.25em;">We, at %s, '
                                   'process your provided information in order to organize the best possible hackathon. This '
                                   'may also include images and videos featuring you during the event. '
                                   'Your data will be preliminarily used for admissions, and any images or videos '
                                   'may be used for marketing and archiving. '
                                   'For more information on the processing of your '
                                   'personal data and on how to exercise your rights of access, '
                                   'rectification, suppression, limitation, portability and opposition '
                                   'please visit our Privacy and Cookies Policy.</p>' %
                                   getattr(settings, 'HACKATHON_ORG')
                }})
        fields[next(iter(fields))]['fields'].append({'name': 'promotional_code'})
        return fields

    def get_policy_fields(self):
        # Added MLH required checkboxes
        return [
            {'name': 'terms_and_conditions', 'space': 12},
            {'name': 'diet_notice', 'space': 12},
            {'name': 'mlh_data', 'space': 12},
            {'name': 'mlh_emails', 'space': 12},
        ]

    def clean_promotional_code(self):
        promotional_code = self.cleaned_data.get('promotional_code', None)
        if promotional_code is not None:
            if promotional_code.usages != -1 and promotional_code.application_set.count() >= promotional_code.usages:
                raise ValidationError('This code is out of usages or not for this type')
        return promotional_code

    def clean(self):
        cleaned = super().clean()
        # Enforce required MLH data sharing checkbox on initial application only
        # (on edit, this field is not required and may be hidden)
        if not is_instance_on_db(getattr(self, 'instance', None)):
            if 'mlh_data' in self.fields and not cleaned.get('mlh_data'):
                self.add_error('mlh_data', _('This field is required.'))
        return cleaned

    class Meta:
        model = Application
        description = ''
        exclude = ['user', 'uuid', 'data', 'submission_date', 'status_update_date', 'status', 'contacted_by', 'type',
                   'last_modified', 'edition']
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
        }
        widgets = {
            'promotional_code': forms.HiddenInput
        }
