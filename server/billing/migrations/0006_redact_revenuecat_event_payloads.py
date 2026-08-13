import uuid

from django.db import migrations

IDENTITY_KEYS = {
    "appUserId",
    "app_user_id",
    "originalAppUserId",
    "original_app_user_id",
    "aliases",
    "transferredFrom",
    "transferred_from",
    "transferredTo",
    "transferred_to",
}


def identity_values(value):
    if not isinstance(value, dict):
        return []
    found = []
    for key, item in value.items():
        if key in IDENTITY_KEYS:
            if isinstance(item, list):
                found.extend(candidate for candidate in item if isinstance(candidate, str))
            elif isinstance(item, str):
                found.append(item)
        elif isinstance(item, dict):
            found.extend(identity_values(item))
    return found


def parsed_uuid(value):
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


def redact_event_payloads(apps, schema_editor):
    RevenueCatEvent = apps.get_model("billing", "RevenueCatEvent")
    Account = apps.get_model("identity", "Account")
    for event in RevenueCatEvent.objects.all().iterator():
        candidates = [event.app_user_id, *identity_values(event.payload)]
        candidate_ids = {parsed for value in candidates if (parsed := parsed_uuid(value))}
        survivors = list(
            Account.objects.filter(pk__in=candidate_ids).values_list("pk", flat=True)[:2]
        )
        event.app_user_id = str(survivors[0]) if len(survivors) == 1 else ""
        event.payload = {"redacted": True}
        event.save(update_fields=["app_user_id", "payload"])


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0005_accountentitlement_authority_observed_at"),
    ]

    operations = [
        migrations.RunPython(redact_event_payloads, migrations.RunPython.noop),
    ]
