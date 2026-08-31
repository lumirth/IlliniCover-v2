from unittest.mock import patch

import pytest
from django.core.management.base import CommandError
from django.db.migrations.recorder import MigrationRecorder

from product.management.commands.verify_deploy_database import Command, database_state

MIGRATION_TABLE = MigrationRecorder.Migration._meta.db_table


def test_deploy_database_state_accepts_only_empty_or_current_schema():
    assert database_state(set(), set()) == "empty"
    assert database_state({"unmanaged_table"}, set()) == "incompatible"
    assert database_state({MIGRATION_TABLE}, {("covers", "0009_old")}) == "incompatible"
    assert database_state(
        {MIGRATION_TABLE, "product_venue"},
        {("auth", "0012_alter_user_first_name_max_length"), ("product", "0001_initial")},
    ) == "current"


@patch("product.management.commands.verify_deploy_database.connection")
def test_empty_database_requires_explicit_cutover(connection):
    connection.introspection.table_names.return_value = []
    with pytest.raises(CommandError, match="PREALPHA_CUTOVER=true"):
        Command().handle(allow_empty=False)
    Command().handle(allow_empty=True)


@patch("product.management.commands.verify_deploy_database.MigrationRecorder")
@patch("product.management.commands.verify_deploy_database.connection")
def test_cutover_never_accepts_an_old_database(connection, recorder):
    connection.introspection.table_names.return_value = [MIGRATION_TABLE, "covers_coverdecision"]
    recorder.return_value.applied_migrations.return_value = {("covers", "0009_old")}
    with pytest.raises(CommandError, match="incompatible pre-reset schema"):
        Command().handle(allow_empty=True)
