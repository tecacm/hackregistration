from __future__ import annotations

import copy

from django.db import migrations
from django.db.models import Max


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


TRACK_SPECS = [
    {
        "track": "interactive_media",
        "name": "Smart Intelligence by GateGroup",
        "definition": SMART_INTELLIGENCE_DEFINITION,
        "aliases": [
            "smart intelligence",
            "smart intelligence by gategroup",
            "smart_intelligence",
            "interactive media",
        ],
    },
    {
        "track": "social_good",
        "name": "Smart Execution by GateGroup",
        "definition": SMART_EXECUTION_DEFINITION,
        "aliases": [
            "smart execution",
            "smart execution by gategroup",
            "smart_execution",
            "social good",
        ],
    },
]


def ensure_gate_group_rubrics(apps, schema_editor):
    Edition = apps.get_model("application", "Edition")
    JudgingRubric = apps.get_model("judging", "JudgingRubric")

    for edition in Edition.objects.all():
        for spec in TRACK_SPECS:
            definition = copy.deepcopy(spec["definition"])
            canonical_qs = (
                JudgingRubric.objects
                .filter(edition=edition, track__iexact=spec["track"])
                .order_by("-version")
            )
            rubric = canonical_qs.first()

            if rubric is None:
                for alias in spec["aliases"]:
                    alias_rubric = (
                        JudgingRubric.objects
                        .filter(edition=edition, track__iexact=alias)
                        .order_by("-version")
                        .first()
                    )
                    if alias_rubric:
                        rubric = alias_rubric
                        break

            if rubric is not None:
                needs_update = False
                if rubric.track != spec["track"]:
                    rubric.track = spec["track"]
                    needs_update = True
                if rubric.name != spec["name"]:
                    rubric.name = spec["name"]
                    needs_update = True
                if rubric.definition != spec["definition"]:
                    rubric.definition = copy.deepcopy(spec["definition"])
                    needs_update = True
                if not rubric.is_active:
                    rubric.is_active = True
                    needs_update = True
                if needs_update:
                    rubric.save()
                continue

            next_version = (
                JudgingRubric.objects
                .filter(edition=edition, track__iexact=spec["track"])
                .aggregate(max_version=Max("version"))
                .get("max_version")
                or 0
            ) + 1

            JudgingRubric.objects.create(
                edition=edition,
                name=spec["name"],
                version=next_version,
                track=spec["track"],
                definition=definition,
                is_active=True,
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("judging", "0005_create_fintech_rubric"),
    ]

    operations = [
        migrations.RunPython(ensure_gate_group_rubrics, noop),
    ]
