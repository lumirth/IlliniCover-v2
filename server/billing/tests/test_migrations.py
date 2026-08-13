import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

PREVIOUS = ("billing", "0003_alter_providerdeletionrequest_status")
LATEST = ("billing", "0006_redact_revenuecat_event_payloads")


@pytest.mark.django_db(transaction=True)
def test_environment_migration_preserves_legacy_access_as_provider_aggregate():
    executor = MigrationExecutor(connection)
    executor.migrate([PREVIOUS])
    old_apps = executor.loader.project_state([PREVIOUS]).apps
    OldAccount = old_apps.get_model("identity", "Account")
    OldEntitlement = old_apps.get_model("billing", "AccountEntitlement")
    OldEvent = old_apps.get_model("billing", "RevenueCatEvent")
    account_id = uuid.uuid4()
    alias_account_id = uuid.uuid4()
    deleted_alias_id = uuid.uuid4()

    try:
        OldAccount.objects.create(
            id=account_id,
            email="legacy-billing@example.com",
            password="!",
        )
        OldAccount.objects.create(
            id=alias_account_id,
            email="legacy-alias@example.com",
            password="!",
        )
        OldEntitlement.objects.create(account_id=account_id, is_active=True)
        OldEvent.objects.create(
            provider_event_id="legacy-sandbox-event",
            event_type="INITIAL_PURCHASE",
            app_user_id=str(account_id),
            payload={"event": {"environment": "SANDBOX"}},
        )
        OldEvent.objects.create(
            provider_event_id="legacy-mixed-identity-event",
            event_type="TRANSFER",
            app_user_id=str(deleted_alias_id),
            payload={
                "event": {
                    "aliases": [str(deleted_alias_id), str(alias_account_id)],
                    "transferredFrom": [str(deleted_alias_id)],
                    "transferredTo": [str(alias_account_id)],
                }
            },
        )

        executor = MigrationExecutor(connection)
        executor.migrate([LATEST])
        new_apps = executor.loader.project_state([LATEST]).apps
        NewEntitlement = new_apps.get_model("billing", "AccountEntitlement")
        NewEvent = new_apps.get_model("billing", "RevenueCatEvent")

        entitlement = NewEntitlement.objects.get(account_id=account_id)
        event = NewEvent.objects.get(provider_event_id="legacy-sandbox-event")
        mixed_event = NewEvent.objects.get(provider_event_id="legacy-mixed-identity-event")
        assert entitlement.environment == "provider_aggregate"
        assert entitlement.is_active is True
        assert entitlement.authority_observed_at == entitlement.updated_at
        assert event.environment == "sandbox"
        assert event.app_user_id == str(account_id)
        assert event.payload == {"redacted": True}
        assert mixed_event.app_user_id == str(alias_account_id)
        assert mixed_event.payload == {"redacted": True}
    finally:
        MigrationExecutor(connection).migrate([LATEST])
