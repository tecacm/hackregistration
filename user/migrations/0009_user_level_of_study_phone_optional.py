from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0008_remove_user_under_age_user_birth_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='level_of_study',
            field=models.CharField(blank=True, max_length=60, null=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='phone_number',
            field=models.CharField(blank=True, help_text="Phone number must be entered in the format: +#########. Up to 15 digits allowed.", max_length=20, validators=[django.core.validators.RegexValidator(regex='^\\+?1?\\d{9,15}$')]),
        ),
    ]
