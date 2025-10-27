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


TRACK_ALIASES = {
    "fintech": CAPITAL_ONE_DEFINITION,
    "fintech by capital one": CAPITAL_ONE_DEFINITION,
    "capital one": CAPITAL_ONE_DEFINITION,
}


def update_capital_one_rubrics(apps, schema_editor):
    JudgingRubric = apps.get_model("judging", "JudgingRubric")
    for rubric in JudgingRubric.objects.all():
        track_value = (rubric.track or "").strip().lower()
        definition = TRACK_ALIASES.get(track_value)
        if definition is None:
            continue
        rubric.definition = copy.deepcopy(definition)
        rubric.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("judging", "0003_update_gate_group_rubrics"),
    ]

    operations = [
        migrations.RunPython(update_capital_one_rubrics, noop),
    ]
