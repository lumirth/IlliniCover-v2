import json
import re
import unicodedata
from pathlib import Path

from django.conf import settings
from django.db import migrations, models


def normalize_search_text(value):
    decomposed = unicodedata.normalize("NFD", value.strip().casefold())
    without_marks = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    without_apostrophes = without_marks.replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[&/+]+|[^a-z0-9]+", " ", without_apostrophes).split())


def backfill_search_aliases(apps, schema_editor):
    historical_fact = apps.get_model("deals", "HistoricalDealFact")
    dataset = (
        Path(settings.REPOSITORY_DIR)
        / "data"
        / "deals"
        / "historical-deals-v1"
        / "historical-deals-v1.jsonl"
    )
    if not dataset.is_file():
        if historical_fact.objects.exists():
            raise RuntimeError("historical deal source is required to backfill search aliases")
        return
    aliases = {}
    with dataset.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            alias = normalize_search_text(row.get("raw_name") or "")
            if alias:
                aliases[row["source_record_key"]] = alias
    for source_key, alias in aliases.items():
        historical_fact.objects.filter(source_record_key=source_key).update(
            private_search_text=alias
        )


def clear_search_aliases(apps, schema_editor):
    historical_fact = apps.get_model("deals", "HistoricalDealFact")
    historical_fact.objects.update(private_search_text="")


class Migration(migrations.Migration):
    dependencies = [("deals", "0007_dealevidenceevent_target_evidence")]

    operations = [
        migrations.AddField(
            model_name="historicaldealfact",
            name="private_search_text",
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.RunPython(backfill_search_aliases, clear_search_aliases),
    ]
