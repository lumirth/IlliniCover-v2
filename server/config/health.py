from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse


def live(request):
    return JsonResponse({"status": "ok"})


def ready(request):
    if getattr(settings, "DEPLOYMENT_ENVIRONMENT", "") in {"production", "preview"}:
        required_integrations = (
            settings.EMAIL_HOST,
            settings.EMAIL_HOST_USER,
            settings.EMAIL_HOST_PASSWORD,
            settings.REVENUECAT_WEBHOOK_AUTHORIZATION,
            settings.REVENUECAT_WEBHOOK_SIGNING_SECRET,
            settings.REVENUECAT_SECRET_API_KEY,
        )
        if not all(value.strip() for value in required_integrations):
            return JsonResponse({"status": "not_ready"}, status=503)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        return JsonResponse({"status": "not_ready"}, status=503)
    return JsonResponse({"status": "ready"})
