from django.db import migrations


def add_volunteers_to_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Application = apps.get_model('application', 'Application')
    User = apps.get_model('user', 'User')

    group, _ = Group.objects.get_or_create(name='Volunteer')
    volunteer_user_ids = Application.objects.filter(
        type__name__iexact='Volunteer',
        status__in=['C', 'A'],
    ).values_list('user_id', flat=True).distinct()
    if not volunteer_user_ids:
        return
    users = list(User.objects.filter(id__in=volunteer_user_ids))
    if users:
        group.user_set.add(*users)


def remove_volunteers_from_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Application = apps.get_model('application', 'Application')
    User = apps.get_model('user', 'User')

    try:
        group = Group.objects.get(name='Volunteer')
    except Group.DoesNotExist:
        return
    volunteer_user_ids = Application.objects.filter(
        type__name__iexact='Volunteer',
        status__in=['C', 'A'],
    ).values_list('user_id', flat=True).distinct()
    if not volunteer_user_ids:
        return
    users = list(User.objects.filter(id__in=volunteer_user_ids))
    if users:
        group.user_set.remove(*users)


class Migration(migrations.Migration):

    dependencies = [
        ('event', '0001_volunteer_permissions'),
        ('application', '0039_broadcast_image_fields'),
        ('user', '0015_alter_user_judge_type'),
    ]

    operations = [
        migrations.RunPython(add_volunteers_to_group, reverse_code=remove_volunteers_from_group),
    ]
