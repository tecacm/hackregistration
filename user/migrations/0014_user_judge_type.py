import json

from django.db import migrations, models
from django.utils import timezone


def create_judge_applications(apps, schema_editor):
    Application = apps.get_model('application', 'Application')
    ApplicationTypeConfig = apps.get_model('application', 'ApplicationTypeConfig')
    Edition = apps.get_model('application', 'Edition')
    Group = apps.get_model('auth', 'Group')
    User = apps.get_model('user', 'User')

    edition = Edition.objects.order_by('-order').first()
    if edition is None:
        return

    judge_type, created = ApplicationTypeConfig.objects.get_or_create(
        name='Judge',
        defaults={
            'start_application_date': timezone.now(),
            'end_application_date': timezone.now() + timezone.timedelta(days=365),
            'vote': False,
            'dubious': False,
            'auto_confirm': True,
            'compatible_with_others': True,
            'create_user': False,
            'hidden': True,
        },
    )

    Group.objects.get_or_create(name='Judge')

    judge_users = User.objects.filter(groups__name='Judge').distinct()
    if not judge_users.exists():
        return

    for user in judge_users:
        application, _ = Application.objects.get_or_create(
            user=user,
            type=judge_type,
            edition=edition,
            defaults={
                'status': Application.STATUS_CONFIRMED,
                'submission_date': timezone.now(),
                'last_modified': timezone.now(),
                'status_update_date': timezone.now(),
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


def noop_reverse(apps, schema_editor):
    # We intentionally keep judge applications for audit history.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0013_alter_user_last_name_alter_user_tshirt_size'),
        ('application', '0038_edition_judging_scores_public'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='judge_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('technical', 'Technical / Engineering'),
                    ('product', 'Product / UX / Research'),
                    ('business', 'Business / Strategy / Operations'),
                    ('sponsor', 'Sponsor / Partner / Donor'),
                    ('other', 'Other / Generalist'),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(create_judge_applications, noop_reverse),
    ]
