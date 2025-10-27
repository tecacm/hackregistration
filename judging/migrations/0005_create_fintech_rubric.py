from __future__ import annotations

import copy

from django.db import migrations


CAPITAL_ONE_DEFINITION = {
    "sections": [
        {
            "id": "capital_one_overview",
            "title": "Fintech by Capital One",
            "weight": 1.0,
            "criteria": [
                {"id": "capital_one_creativity", "label": "Creativity", "max_score": 5},
                {"id": "capital_one_complexity", "label": "Complexity", "max_score": 5},
                {"id": "capital_one_completeness", "label": "Completeness", "max_score": 5},
                {"id": "capital_one_impact", "label": "Impact", "max_score": 5},
            ],
        }
    ],
}

TRACK_NAME = "fintech"


def create_fintech_rubric(apps, schema_editor):
    Edition = apps.get_model("application", "Edition")
    JudgingRubric = apps.get_model("judging", "JudgingRubric")

    for edition in Edition.objects.all():
        existing = (
            JudgingRubric.objects
            .filter(edition=edition, track__iexact=TRACK_NAME)
            .order_by("-version")
            .first()
        )
        if existing:
            continue
        general = (
            JudgingRubric.objects
            .filter(edition=edition, track='')
            .order_by("-version")
            .first()
        )
        version = 1
        rubric = JudgingRubric.objects.create(
            edition=edition,
            name="Fintech by Capital One",
            version=version,
            track=TRACK_NAME,
            definition=copy.deepcopy(CAPITAL_ONE_DEFINITION),
            is_active=True,
        )
        if general and general.is_active:
            # keep general active but ensure newest track-specific remains active
            JudgingRubric.objects.filter(
                edition=edition,
                track__iexact=TRACK_NAME,
            ).exclude(pk=rubric.pk).update(is_active=False)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("judging", "0004_update_capital_one_rubric"),
    ]

    operations = [
        migrations.RunPython(create_fintech_rubric, noop),
    ]
