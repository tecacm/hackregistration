from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from application.models import Edition

from judging.models import JudgingRubric


class Command(BaseCommand):
    help = "Import judging rubric definitions from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument("edition", type=int, help="ID of the edition to attach the rubric to")
        parser.add_argument("path", type=str, help="Path to the JSON file containing the rubric definition")
        parser.add_argument(
            "--name",
            dest="name",
            type=str,
            default="Imported rubric",
            help="Optional name for the new rubric (default: Imported rubric)",
        )
        parser.add_argument(
            "--rubric-version",
            dest="version",
            type=int,
            default=None,
            help="Optional rubric version number. If omitted, the next version number is used automatically.",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Mark the imported rubric as the active rubric for the edition.",
        )
        parser.add_argument(
            "--track",
            dest="track",
            type=str,
            default="",
            help="Optional track name this rubric applies to. Leave blank for general use.",
        )

    def handle(self, *args, **options):
        edition_id: int = options["edition"]
        path_str: str = options["path"]
        name: str = options["name"]
        version: int | None = options["version"]
        activate: bool = options["activate"]
        track: str = options["track"] or ""

        try:
            edition = Edition.objects.get(pk=edition_id)
        except Edition.DoesNotExist as exc:  # pragma: no cover - defensive
            raise CommandError(f"Edition with ID {edition_id} does not exist") from exc

        path = Path(path_str)
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        try:
            definition = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {path}: {exc}") from exc

        if not isinstance(definition, dict):
            raise CommandError("The JSON file must contain an object at the top level.")

        normalized_track = track.strip()

        if version is None:
            latest = (
                JudgingRubric.objects
                .filter(edition=edition, track__iexact=normalized_track)
                .order_by("-version")
                .first()
            )
            version = 1 if latest is None else latest.version + 1

        rubric = JudgingRubric(
            edition=edition,
            name=name,
            version=version,
            track=normalized_track,
            definition=definition,
            is_active=activate,
        )

        rubric.full_clean()
        rubric.save()

        if activate:
            JudgingRubric.objects.filter(edition=edition, track__iexact=normalized_track).exclude(pk=rubric.pk).update(is_active=False)

        self.stdout.write(self.style.SUCCESS(f"Imported rubric '{rubric.name}' version {rubric.version} for {edition}."))
