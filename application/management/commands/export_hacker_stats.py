import csv
import os
import unicodedata

from django.core.management.base import BaseCommand

from application.models import Application


class Command(BaseCommand):
    help = "Export basic hacker application statistics to a CSV file."

    MEXICO_NAME_MAP = (
        ("cdmx", "Ciudad de México"),
        ("ciudad de mexico", "Ciudad de México"),
        ("mexico city", "Ciudad de México"),
        ("mexico,", "Ciudad de México"),
        ("mexico", "Ciudad de México"),
        ("guadalajara", "Guadalajara"),
        ("hermosillo", "Hermosillo"),
        ("saltillo", "Saltillo"),
        ("san nicolas", "San Nicolás de los Garza"),
        ("san nicolás", "San Nicolás de los Garza"),
        ("san pedro garza garcia", "San Pedro Garza García"),
        ("san pedro garza garcía", "San Pedro Garza García"),
        ("san pedro", "San Pedro Garza García"),
        ("san pedro de las colonias", "San Pedro de las Colonias"),
        ("san pedro coahuila", "San Pedro de las Colonias"),
        ("torreon", "Torreón"),
        ("torreón", "Torreón"),
        ("torreon coah", "Torreón"),
        ("torreon coahuila", "Torreón"),
        ("torreón coahuila", "Torreón"),
        ("torreon,", "Torreón"),
        ("monterey", "Monterrey"),
        ("monterry", "Monterrey"),
        ("monterrey", "Monterrey"),
        ("monterrey nuevo leon", "Monterrey"),
        ("monterrey nuevo león", "Monterrey"),
        ("monterrey,", "Monterrey"),
        ("onterrey", "Monterrey"),
        ("spgg", "San Pedro Garza García"),
        ("nuevo leon", "Nuevo León"),
        ("nuevo león", "Nuevo León"),
        ("juarez n.l", "Juárez"),
        ("juárez n.l", "Juárez"),
        ("juarez", "Juárez"),
        ("san luis potosi", "San Luis Potosí"),
        ("san luis potosí", "San Luis Potosí"),
        ("queretaro", "Querétaro"),
        ("querétaro", "Querétaro"),
        ("merida", "Mérida"),
        ("mérida", "Mérida"),
        ("apodaca", "Apodaca"),
        ("guadalupe", "Guadalupe"),
        ("coahuila", "Coahuila"),
        ("puebla", "Puebla"),
        ("durango", "Durango"),
        ("ciudad de durrango", "Durango"),
        ("mexicali", "Mexicali"),
        ("monclova", "Monclova"),
        ("zacatecas", "Zacatecas"),
        ("sonora", "Sonora"),
        ("zacatepec", "Zacatepec"),
        ("victoria", "Ciudad Victoria"),
        ("san jose iturbide", "San José Iturbide"),
        ("villa de alvarez", "Villa de Álvarez"),
        ("francisco i madero", "Francisco I. Madero"),
        ("francisco i. madero", "Francisco I. Madero"),
        ("pachuca de soto hidalgo", "Pachuca de Soto"),
        ("pachuca de soto", "Pachuca de Soto"),
        ("minatitlan", "Minatitlán"),
        ("lerdo", "Lerdo"),
        ("city", "Unknown"),
    )

    OTHER_ORIGIN_MAP = (
        ("bogota", "Bogotá"),
        ("valparaiso", "Valparaíso"),
        ("san cristobal", "San Cristóbal"),
        ("santa cruz de la sierra", "Santa Cruz de la Sierra"),
    )

    COUNTRY_NAME_MAP = {
        "estados unidos": "United States of America",
        "estados unidos de america": "United States of America",
        "usa": "United States of America",
        "united states": "United States of America",
        "united states of america": "United States of America",
        "méxico": "Mexico",
        "mexico": "Mexico",
        "others": "Other / Unspecified",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="tmp/hacker_stats.csv",
            help="Absolute or relative path for the CSV export (default: tmp/hacker_stats.csv).",
        )

    def handle(self, *args, **options):
        output_path = options["output"]
        hacker_apps = Application.objects.actual().filter(type__name__iexact="Hacker")
        total_applications = hacker_apps.count()

        confirmed_statuses = {Application.STATUS_CONFIRMED, Application.STATUS_ATTENDED}
        confirmed_apps = hacker_apps.filter(status__in=confirmed_statuses)
        total_confirmed = confirmed_apps.count()

        mexico_totals = {}
        international_totals = {}

        for application in confirmed_apps.iterator():
            form_data = application.form_data
            origin_value = self._canonicalize_origin(form_data.get("origin"))
            country_value = self._canonicalize_country(form_data.get("country"))

            if self._is_mexico(country_value):
                bucket = mexico_totals
                origin_key = self._normalize(origin_value)
                entry = bucket.setdefault(
                    origin_key,
                    {"origin": origin_value, "count": 0},
                )
                entry["count"] += 1
            else:
                bucket = international_totals
                country_key = self._normalize(country_value)
                origin_key = self._normalize(origin_value)
                entry = bucket.setdefault(
                    (country_key, origin_key),
                    {
                        "country": country_value,
                        "origin": origin_value,
                        "count": 0,
                    },
                )
                entry["count"] += 1

        mexico_rows = sorted(
            mexico_totals.values(),
            key=lambda item: (-item["count"], self._normalize(item["origin"])),
        )
        international_rows = sorted(
            international_totals.values(),
            key=lambda item: (
                -item["count"],
                self._normalize(item["country"]),
                self._normalize(item["origin"]),
            ),
        )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["segment", "country", "origin", "count"])
            writer.writerow(["total_applications", "", "", total_applications])
            writer.writerow(["total_confirmed", "", "", total_confirmed])

            for row in mexico_rows:
                writer.writerow(["confirmed_mexico", "Mexico", row["origin"], row["count"]])

            for row in international_rows:
                writer.writerow([
                    "confirmed_international",
                    row["country"],
                    row["origin"],
                    row["count"],
                ])

        absolute_path = os.path.abspath(output_path)
        self.stdout.write(self.style.SUCCESS(f"Exported hacker stats to {absolute_path}"))

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
        return ascii_only.strip().lower()

    def _title_case(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            return "Unknown"
        words = cleaned.split()
        if not words:
            return "Unknown"
        connectors = {"de", "del", "la", "las", "los", "y", "e", "of"}
        result = []
        for index, word in enumerate(words):
            lower = word.lower()
            if index > 0 and lower in connectors:
                result.append(lower)
            elif len(word) > 1 and word.isupper():
                result.append(word)
            else:
                result.append(lower.capitalize())
        return " ".join(result)

    def _canonicalize_origin(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            return "Unknown"

        normalized = self._normalize(cleaned)

        for pattern, canonical in self.MEXICO_NAME_MAP:
            if pattern in normalized:
                return canonical

        if "," in cleaned:
            cleaned = cleaned.split(",", 1)[0].strip()

        normalized = self._normalize(cleaned)
        for pattern, canonical in self.OTHER_ORIGIN_MAP:
            if pattern in normalized:
                return canonical

        return self._title_case(cleaned)

    def _canonicalize_country(self, value: str) -> str:
        cleaned = (value or "").strip()
        normalized = self._normalize(cleaned)
        if not normalized:
            return "Unknown"
        if normalized in self.COUNTRY_NAME_MAP:
            return self.COUNTRY_NAME_MAP[normalized]
        return self._title_case(cleaned)

    def _is_mexico(self, country_value: str) -> bool:
        normalized = self._normalize(country_value)
        if not normalized:
            return False
        return normalized == "mexico"
