from __future__ import annotations

import copy

from django.db import migrations


SMART_INTELLIGENCE_DEFINITION = {
    "sections": [
        {
            "id": "expiration_date",
            "title": "Expiration date",
            "weight": 0.34,
            "criteria": [
                {"id": "expiration_innovation", "label": "Innovation", "max_score": 6},
                {"id": "expiration_feasibility", "label": "Feasibility", "max_score": 6},
                {"id": "expiration_efficiency", "label": "Efficiency", "max_score": 6},
                {"id": "expiration_sustainability", "label": "Sustainability", "max_score": 6},
                {"id": "expiration_user_experience", "label": "User experience", "max_score": 6},
            ],
        },
        {
            "id": "consumption_prediction",
            "title": "Consumption prediction",
            "weight": 0.33,
            "criteria": [
                {"id": "consumption_innovation", "label": "Innovation", "max_score": 6},
                {"id": "consumption_feasibility", "label": "Feasibility", "max_score": 6},
                {"id": "consumption_efficiency", "label": "Efficiency", "max_score": 6},
                {"id": "consumption_sustainability", "label": "Sustainability", "max_score": 6},
                {"id": "consumption_data_quality", "label": "Data quality & insight", "max_score": 6},
            ],
        },
        {
            "id": "productivity_estimation",
            "title": "Productivity estimation",
            "weight": 0.33,
            "criteria": [
                {"id": "productivity_innovation", "label": "Innovation", "max_score": 6},
                {"id": "productivity_feasibility", "label": "Feasibility", "max_score": 6},
                {"id": "productivity_efficiency", "label": "Efficiency", "max_score": 6},
                {"id": "productivity_user_experience", "label": "User experience", "max_score": 6},
                {"id": "productivity_scalability", "label": "Scalability & standardisation", "max_score": 6},
            ],
        },
    ],
}


SMART_EXECUTION_DEFINITION = {
    "sections": [
        {
            "id": "smart_execution_overview",
            "title": "Smart execution",
            "weight": 1.0,
            "criteria": [
                {"id": "execution_innovation", "label": "Innovation", "max_score": 6},
                {"id": "execution_feasibility", "label": "Feasibility", "max_score": 6},
                {"id": "execution_efficiency", "label": "Efficiency", "max_score": 6},
                {"id": "execution_sustainability", "label": "Sustainability", "max_score": 6},
                {"id": "execution_user_experience", "label": "User experience", "max_score": 6},
            ],
        }
    ],
}


TRACK_ALIASES = {
    "interactive_media": SMART_INTELLIGENCE_DEFINITION,
    "smart intelligence": SMART_INTELLIGENCE_DEFINITION,
    "smart intelligence by gategroup": SMART_INTELLIGENCE_DEFINITION,
    "social_good": SMART_EXECUTION_DEFINITION,
    "smart execution": SMART_EXECUTION_DEFINITION,
    "smart execution by gategroup": SMART_EXECUTION_DEFINITION,
}


def update_gate_group_rubrics(apps, schema_editor):
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
        ("judging", "0002_judgingrubric_track"),
    ]

    operations = [
        migrations.RunPython(update_gate_group_rubrics, noop),
    ]
