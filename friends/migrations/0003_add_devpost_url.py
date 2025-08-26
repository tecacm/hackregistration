from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('friends', '0002_rename_friendcode_friendscode'),
    ]

    operations = [
        migrations.AddField(
            model_name='friendscode',
            name='devpost_url',
            field=models.URLField(blank=True, null=True),
        ),
    ]
