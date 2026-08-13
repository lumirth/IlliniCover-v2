from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("submissions", "0003_submissionratebucket")]

    operations = [
        migrations.AddField(
            model_name="submissionprivatecontext",
            name="evidence_snapshot",
            field=models.JSONField(default=dict),
        )
    ]
