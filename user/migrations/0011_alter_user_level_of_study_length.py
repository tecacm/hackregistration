from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('user', '0010_anonymize_birth_dates'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='level_of_study',
            field=models.CharField(max_length=120, blank=True, null=True),
        ),
    ]
