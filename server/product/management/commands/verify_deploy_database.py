from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

CURRENT_MIGRATION = ("product", "0001_initial")
ALLOWED_MIGRATION_APPS = {
    "account",
    "admin",
    "auth",
    "contenttypes",
    "mfa",
    "product",
    "sessions",
    "sites",
}


def database_state(tables, applied):
    if not tables:
        return "empty"
    if MigrationRecorder.Migration._meta.db_table not in tables:
        return "incompatible"
    apps = {app for app, _name in applied}
    if apps - ALLOWED_MIGRATION_APPS or CURRENT_MIGRATION not in applied:
        return "incompatible"
    return "current"


class Command(BaseCommand):
    help = "Refuse deployment onto a pre-reset or otherwise incompatible database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-empty",
            action="store_true",
            help=(
                "Allow a deliberately provisioned empty database for the one-time pre-alpha "
                "cutover."
            ),
        )

    def handle(self, *, allow_empty=False, **options):
        tables = set(connection.introspection.table_names())
        applied = MigrationRecorder(connection).applied_migrations() if tables else set()
        state = database_state(tables, applied)
        if state == "current":
            self.stdout.write("database is compatible with the current application schema")
            return
        if state == "empty" and allow_empty:
            self.stdout.write("empty database accepted for explicit pre-alpha cutover")
            return
        if state == "empty":
            raise CommandError("empty database requires PREALPHA_CUTOVER=true")
        raise CommandError(
            "database belongs to an incompatible pre-reset schema; point both secret bundles at "
            "a fresh database and run the explicit pre-alpha cutover"
        )
