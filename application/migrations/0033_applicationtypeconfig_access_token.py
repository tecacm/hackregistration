from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('application', '0032_permissionslip'),
    ]

    operations = [
        migrations.AddField(
            model_name='applicationtypeconfig',
            name='access_token',
            field=models.CharField(blank=True, help_text='Optional secret token required to access apply form when hidden (share the link ?type=Type&token=ACCESS_TOKEN)', max_length=64),
        ),
    ]
