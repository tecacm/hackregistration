from django.db import migrations, models
from django.conf import settings
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('application', '0035_edition_track_selection_open_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Broadcast',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('run_id', models.CharField(db_index=True, max_length=128)),
                ('subject', models.CharField(max_length=200)),
                ('message', models.TextField()),
                ('application_type', models.CharField(max_length=64)),
                ('max_team_size', models.PositiveIntegerField(default=3)),
                ('include_no_team', models.BooleanField(default=True)),
                ('allowed_statuses', models.CharField(help_text='Comma-separated statuses.', max_length=128)),
                ('edition_id', models.IntegerField()),
                ('status', models.CharField(choices=[('P', 'Pending'), ('R', 'Running'), ('C', 'Completed'), ('F', 'Failed')], default='P', max_length=1)),
                ('total', models.PositiveIntegerField(default=0)),
                ('accepted', models.PositiveIntegerField(default=0)),
                ('errors', models.TextField(blank=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='BroadcastRecipient',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('email', models.EmailField(max_length=254)),
                ('status', models.CharField(choices=[('P', 'Pending'), ('S', 'Sent'), ('F', 'Failed')], db_index=True, default='P', max_length=1)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('last_error', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='application.application')),
                ('broadcast', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recipients', to='application.broadcast')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['broadcast', 'status'], name='brc_broadcast_status_idx'),
                    models.Index(fields=['email'], name='brc_email_idx'),
                ],
            },
        ),
    ]
