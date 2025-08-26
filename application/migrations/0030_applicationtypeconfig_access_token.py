from django.db import migrations


class Migration(migrations.Migration):
	"""No-op migration replacing removed broken migration 0030_applicationtypeconfig_access_token.

	Keeps dependency chain intact: 0029 -> 0030(no-op) -> 0030_draftapplication -> 0031 ...
	"""

	dependencies = [
		('application', '0029_applicationtypeconfig_spots'),
	]

	operations = []
