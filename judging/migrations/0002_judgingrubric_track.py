from django.db import migrations, models


def normalize_tracks(apps, schema_editor):
    JudgingRubric = apps.get_model('judging', 'JudgingRubric')
    for rubric in JudgingRubric.objects.all():
        track = (rubric.track or '').strip()
        if rubric.track != track:
            rubric.track = track
            rubric.save(update_fields=['track'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('judging', '0002_judgeinvitecode'),
    ]

    operations = [
        migrations.AddField(
            model_name='judgingrubric',
            name='track',
            field=models.CharField(blank=True, default='', help_text='Optional track name this rubric applies to. Leave blank for general use.', max_length=80),
        ),
        migrations.AlterUniqueTogether(
            name='judgingrubric',
            unique_together={('edition', 'track', 'version')},
        ),
        migrations.RunPython(normalize_tracks, noop),
    ]
