import uuid

import pytest
from django.core.exceptions import FieldDoesNotExist
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

PREVIOUS = ("identity", "0003_accountdeletionreceipt_identityratebucket_and_more")
LATEST = ("identity", "0005_actoraccountlink_attribution_state")


@pytest.mark.django_db(transaction=True)
def test_link_receipt_migration_backfills_and_reverses_multiple_existing_links():
    executor = MigrationExecutor(connection)
    executor.migrate([PREVIOUS])
    old_apps = executor.loader.project_state([PREVIOUS]).apps
    OldAccount = old_apps.get_model("identity", "Account")
    OldActor = old_apps.get_model("identity", "InstallationActor")
    OldLink = old_apps.get_model("identity", "ActorAccountLink")
    expected = {}

    try:
        for index in range(2):
            account_id = uuid.uuid4()
            actor_id = uuid.uuid4()
            request_id = uuid.uuid4()
            OldAccount.objects.create(
                id=account_id,
                email=f"migration-{index}@example.com",
                password="!",
            )
            OldActor.objects.create(id=actor_id)
            link = OldLink.objects.create(
                actor_id=actor_id,
                account_id=account_id,
                request_id=request_id,
            )
            expected[link.pk] = request_id

        executor = MigrationExecutor(connection)
        executor.migrate([LATEST])
        new_apps = executor.loader.project_state([LATEST]).apps
        NewLink = new_apps.get_model("identity", "ActorAccountLink")
        LinkReceipt = new_apps.get_model("identity", "ActorAccountLinkReceipt")

        with pytest.raises(FieldDoesNotExist):
            NewLink._meta.get_field("request_id")
        assert {
            receipt.link_id: receipt.request_id for receipt in LinkReceipt.objects.all()
        } == expected
        assert set(NewLink.objects.values_list("is_attribution_active", flat=True)) == {True}

        executor = MigrationExecutor(connection)
        executor.migrate([PREVIOUS])
        restored_apps = executor.loader.project_state([PREVIOUS]).apps
        RestoredLink = restored_apps.get_model("identity", "ActorAccountLink")
        assert {link.pk: link.request_id for link in RestoredLink.objects.all()} == expected
    finally:
        MigrationExecutor(connection).migrate([LATEST])
