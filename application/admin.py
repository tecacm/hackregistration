from django import forms
from django.contrib import admin
from django.utils.http import urlencode

from application import models


class ApplicationAdmin(admin.ModelAdmin):
    list_filter = ('type', 'edition')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')


class ApplicationTypeConfigAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from application.views import ApplicationApply
        if 'instance' in kwargs:
            self.initial['file_review_fields'] = kwargs['instance'].get_file_review_fields()
            ApplicationForm = ApplicationApply.get_form_class(kwargs['instance'].name)
            choices = []
            for name, field in ApplicationForm().declared_fields.items():
                if isinstance(field, forms.FileField):
                    choices.append((name, name))
            self.fields['file_review_fields'].widget = forms.CheckboxSelectMultiple(choices=choices)

    class Meta:
        model = models.ApplicationTypeConfig
        fields = '__all__'


class ApplicationTypeConfigAdmin(admin.ModelAdmin):
    form = ApplicationTypeConfigAdminForm
    exclude = ('name', )
    readonly_fields = ('share_link', )
    actions = ('regenerate_access_token', )

    def share_link(self, obj):
        """Readonly helper showing the dynamic apply URL when the type is hidden.

        Example: /application/apply/?type=Sponsor&token=<ACCESS_TOKEN>
        """
        if not obj.hidden:
            return '(visible type — no token required)'
        token = obj.access_token or str(obj.token)
        params = urlencode({'type': obj.name, 'token': token})
        return f"/application/apply/?{params}"

    share_link.short_description = 'Shareable apply link'

    def save_model(self, request, obj, form, change):
        """Ensure hidden types have an access token generated automatically if missing."""
        # If the type is hidden and no explicit access_token is provided, fallback to legacy token
        # or generate a new opaque token for convenience.
        if obj.hidden and not obj.access_token:
            # Prefer a short opaque token that fits in the configured max_length
            try:
                import secrets
                obj.access_token = secrets.token_urlsafe(32)[:64]
            except Exception:
                # As a very last resort keep it empty and rely on the legacy UUID token
                # (the view will accept obj.token when access_token is empty)
                pass
        super().save_model(request, obj, form, change)

    def regenerate_access_token(self, request, queryset):
        """Admin action to rotate the access_token for selected application types."""
        import secrets
        updated = 0
        for obj in queryset:
            obj.access_token = secrets.token_urlsafe(32)[:64]
            obj.save(update_fields=['access_token'])
            updated += 1
        self.message_user(request, f"Regenerated access token for {updated} type(s).")

    regenerate_access_token.short_description = 'Regenerate access token'

    def has_add_permission(self, request, obj=None):
        return False


class PromotionalCodeAdmin(admin.ModelAdmin):
    readonly_fields = ('uuid', )


admin.site.register(models.Application, ApplicationAdmin)
admin.site.register(models.ApplicationTypeConfig, ApplicationTypeConfigAdmin)
admin.site.register(models.ApplicationLog)
admin.site.register(models.Edition)
admin.site.register(models.PermissionSlip)
admin.site.register(models.PromotionalCode, PromotionalCodeAdmin)
