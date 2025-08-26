from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from app.mixins import BootstrapFormMixin


class FriendsForm(BootstrapFormMixin, forms.Form):
    bootstrap_field_info = {'': {'fields': [{'name': 'friends_code', 'space': 12}, ]}}

    friends_code = forms.CharField(label=_('Friends\' code'), max_length=getattr(settings, "FRIEND_CODE_LENGTH", 13),
                                   required=False)


class DevpostForm(BootstrapFormMixin, forms.Form):
    bootstrap_field_info = {'': {'fields': [{'name': 'devpost_url', 'space': 12}, ]}}
    devpost_url = forms.URLField(label=_('Devpost project URL'), required=True)

    def clean_devpost_url(self):
        url = self.cleaned_data['devpost_url']
        # Accept devpost.com and *.devpost.com
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ''
        if not (host == 'devpost.com' or host.endswith('.devpost.com')):
            raise forms.ValidationError(_('Please provide a valid Devpost URL.'))
        return url
