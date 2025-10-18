from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin, GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group

from user.forms import UserChangeForm, UserCreationForm
from user.models import User, BlockedUser


class UserAdmin(BaseUserAdmin):
    permission_field_name = "user_permissions"

    # The forms to add and change user instances
    form = UserChangeForm
    add_form = UserCreationForm

    # The fields to be used in displaying the User model.
    # These override the definitions on the base UserAdmin
    # that reference specific fields on auth.User.
    list_display = ('email', 'first_name', 'last_name', 'judge_type', 'is_staff')
    list_filter = ('judge_type', 'is_staff', 'is_superuser', 'groups')
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': (
            'first_name', 'last_name', 'phone_number', 'level_of_study', 'judge_type', 'diet', 'other_diet', 'gender',
            'other_gender', 'tshirt_size', 'qr_code', 'display_age'
        )}),
    ('Permissions', {'fields': ('email_verified', 'is_staff', 'is_superuser', 'groups', 'user_permissions',
                    'is_active')}),
    ('Important dates', {'fields': ('date_joined', 'last_login')}),
    )
    # add_fieldsets is not a standard ModelAdmin attribute. UserAdmin
    # overrides get_fieldsets to use this attribute when creating a user.
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('first_name', 'last_name', 'email', 'password1', 'password2'),
        }),
    )
    search_fields = ('email', 'first_name', 'last_name', 'level_of_study', 'judge_type')
    ordering = ('email', 'first_name', 'last_name')
    filter_horizontal = ()

    actions = ['anonymize_and_free_email', 'hard_delete_users']

    readonly_fields = ('display_age', 'date_joined', 'last_login')

    def display_age(self, obj):
        return obj.age if obj.age is not None else '—'
    display_age.short_description = 'Age'

    def delete_queryset(self, request, queryset):
        """Custom bulk delete to avoid FK constraint failures.

        Removes dependent objects with restrictive on_delete settings before deleting the users.
        This makes the standard 'Delete selected users' admin action work again.
        """
        from django.db import transaction
        from application.models import Application, ApplicationLog, DraftApplication
        from review.models import Vote, FileReview, CommentReaction
        try:
            with transaction.atomic():
                for user in queryset:
                    # Delete logs where user was the actor (RESTRICT would block user deletion)
                    ApplicationLog.objects.filter(user=user).delete()
                    # Delete applications owned by user (DO_NOTHING would block)
                    apps_qs = Application.objects.filter(user=user)
                    # Deleting applications cascades their logs (related_name='logs'), file reviews via application FK, votes via application FK
                    apps_qs.delete()
                    # Draft applications (DO_NOTHING)
                    DraftApplication.objects.filter(user=user).delete()
                    # Optional cleanup: user-authored review objects with SET_NULL become null automatically; remove if desired
                    # Vote/FileReview/CommentReaction have SET_NULL, we leave them for historical metrics
                    user.delete()
        except Exception as e:
            self.message_user(request, f"Error deleting users: {e}", level='error')
        else:
            self.message_user(request, "Selected users deleted successfully (dependencies removed).")

    def anonymize_and_free_email(self, request, queryset):
        """Anonymize selected users so their email can be reused.

        We can't safely delete users because of FK constraints (Applications, Logs, Votes, etc.).
        This action frees the original email while preserving historical records by:
          - Replacing email with a unique placeholder (keeps row for FKs)
          - Clearing personal fields
          - Marking account inactive & unverified
        After this, a new user can register with the original email.
        """
        updated = 0
        for user in queryset:
            original_email = user.email
            # Skip if already anonymized
            if original_email.startswith('deleted+'):  # heuristic
                continue
            placeholder = f"deleted+{user.pk}@invalid.local"
            user.email = placeholder
            user.first_name = 'Deleted'
            user.last_name = 'User'
            if hasattr(user, 'phone_number'):
                user.phone_number = ''
            if hasattr(user, 'diet'):
                user.diet = ''
            if hasattr(user, 'other_diet'):
                user.other_diet = ''
            if hasattr(user, 'gender'):
                user.gender = ''
            if hasattr(user, 'other_gender'):
                user.other_gender = ''
            user.is_active = False
            if hasattr(user, 'email_verified'):
                user.email_verified = False
            user.save(update_fields=['email','first_name','last_name','phone_number','diet','other_diet','gender','other_gender','is_active','email_verified'] if hasattr(user,'email_verified') else ['email','first_name','last_name','phone_number','diet','other_diet','gender','other_gender','is_active'])
            updated += 1
        self.message_user(request, f"Anonymized {updated} user(s). Original emails can now be reused.")
    anonymize_and_free_email.short_description = 'Anonymize selected users (free email)'

    def hard_delete_users(self, request, queryset):
        """Permanently delete users AND their related data so email can be reused.

        WARNING: This is irreversible and removes applications, votes, logs, drafts, file reviews,
        comment reactions, and invitations tied to the user. Use with caution.
        """
        from django.db import transaction
        from application.models import Application, ApplicationLog, DraftApplication
        from review.models import Vote, FileReview, CommentReaction
        try:
            from friends.models import FriendsCode
        except Exception:  # friends app may be optional
            FriendsCode = None
        deleted = 0
        errors = 0
        for user in queryset:
            try:
                with transaction.atomic():
                    Vote.objects.filter(user=user).delete()
                    FileReview.objects.filter(user=user).delete()
                    CommentReaction.objects.filter(user=user).delete()
                    # Logs where user acted on others' applications
                    ApplicationLog.objects.filter(user=user).delete()
                    # Applications (will cascade delete their logs & file reviews tied via application FK)
                    Application.objects.filter(user=user).delete()
                    DraftApplication.objects.filter(user=user).delete()
                    if FriendsCode is not None:
                        FriendsCode.objects.filter(user=user).delete()
                    # Finally delete the user
                    user.delete()
                deleted += 1
            except Exception:
                errors += 1
        if deleted:
            self.message_user(request, f"Hard-deleted {deleted} user(s). Emails now reusable.")
        if errors:
            self.message_user(request, f"Failed to delete {errors} user(s). Check logs.", level='error')
    hard_delete_users.short_description = 'HARD DELETE selected users (IRREVERSIBLE)'


class GroupAdmin(BaseGroupAdmin):
    permission_field_name = 'permissions'


# Now register the new UserAdmin...
admin.site.register(User, UserAdmin)
admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)
admin.site.register(BlockedUser)
