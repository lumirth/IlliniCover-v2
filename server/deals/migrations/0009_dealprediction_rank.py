from collections import defaultdict

from django.db import migrations, models


def rank_existing_predictions(apps, schema_editor):
    prediction_model = apps.get_model("deals", "DealPrediction")
    grouped = defaultdict(list)
    predictions = prediction_model.objects.all().iterator()
    for prediction in predictions:
        grouped[
            (
                prediction.release_id,
                prediction.venue_id,
                prediction.service_date_local,
            )
        ].append(prediction)

    for rows in grouped.values():
        rows.sort(
            key=lambda prediction: (
                -prediction.support_nights,
                -prediction.latest_evidence_date.toordinal(),
                str(prediction.deal_definition_id),
                str(prediction.id),
            )
        )
        for rank, prediction in enumerate(rows, start=1):
            prediction.rank = rank
        prediction_model.objects.bulk_update(rows, ["rank"])


class Migration(migrations.Migration):
    dependencies = [
        ("deals", "0008_historicaldealfact_search_alias"),
    ]

    operations = [
        migrations.AddField(
            model_name="dealprediction",
            name="rank",
            field=models.PositiveIntegerField(null=True),
        ),
        migrations.RunPython(rank_existing_predictions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="dealprediction",
            name="rank",
            field=models.PositiveIntegerField(),
        ),
        migrations.AddConstraint(
            model_name="dealprediction",
            constraint=models.UniqueConstraint(
                fields=("release", "venue", "service_date_local", "rank"),
                name="unique_deal_prediction_rank",
            ),
        ),
        migrations.AddConstraint(
            model_name="dealprediction",
            constraint=models.CheckConstraint(
                condition=models.Q(("rank__gte", 1)),
                name="deal_prediction_rank_gte_1",
            ),
        ),
    ]
