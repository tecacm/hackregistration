from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('friends', '0008_alter_friendscode_track_assigned_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='friendscode',
            name='track_pref_submitted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
