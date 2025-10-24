from django.db import migrations


def assign_volunteer_permissions(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    content_type, _ = ContentType.objects.get_or_create(app_label='event', model='event')
    required_permissions = [
        ('can_checkin', 'Can checkin'),
        ('can_checkin_meal', 'Can checkin meal'),
    ]

    permission_objects = []
    for codename, default_name in required_permissions:
        permission, _ = Permission.objects.get_or_create(
            codename=codename,
            defaults={'name': default_name, 'content_type': content_type},
        )
        permission_objects.append(permission)

    volunteer_group, _ = Group.objects.get_or_create(name='Volunteer')
    volunteer_group.permissions.add(*permission_objects)


def remove_volunteer_permissions(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    try:
        volunteer_group = Group.objects.get(name='Volunteer')
    except Group.DoesNotExist:
        return

    perms = Permission.objects.filter(codename__in=['can_checkin', 'can_checkin_meal'])
    volunteer_group.permissions.remove(*perms)


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(assign_volunteer_permissions, reverse_code=remove_volunteer_permissions),
    ]
