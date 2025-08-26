from django.db import migrations
from django.utils import timezone


def anonymize_birth_dates(apps, schema_editor):
    User = apps.get_model('user', 'User')
    today = timezone.now().date()
    users = User.objects.exclude(birth_date__isnull=True)
    for u in users.iterator():
        bd = u.birth_date
        if bd.month == today.month and bd.day == today.day:
            # Already synthetic for this scheme; skip
            continue
        # Recompute age based on stored date
        age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        # Synthesize new birth_date keeping only age (set to today minus age years)
        synthetic = today.replace(year=today.year - age)
        if synthetic != bd:
            u.birth_date = synthetic
            u.save(update_fields=['birth_date'])


def reverse_noop(apps, schema_editor):
    # Can't restore original precise birth dates
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0009_user_level_of_study_phone_optional'),
    ]

    operations = [
        migrations.RunPython(anonymize_birth_dates, reverse_noop),
    ]
