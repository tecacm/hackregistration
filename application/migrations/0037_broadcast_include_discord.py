from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('application', '0036_broadcast_outbox'),
    ]

    operations = [
        migrations.AddField(
            model_name='broadcast',
            name='include_discord',
            field=models.BooleanField(default=True, help_text='Whether to include the Discord invite block in messages.'),
        ),
    ]
