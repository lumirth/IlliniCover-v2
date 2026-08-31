from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from product.models import HistoricalDealFact, Submission, Venue


def live(request):
    return JsonResponse({"status": "ok"})


def ready(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    pending = MigrationExecutor(connection).migration_plan(
        MigrationExecutor(connection).loader.graph.leaf_nodes()
    )
    ready_to_serve = (
        not pending
        and Venue.objects.filter(is_active=True).exists()
        and Submission.objects.filter(source_record_key__isnull=False).exists()
        and HistoricalDealFact.objects.exists()
    )
    return JsonResponse(
        {"status": "ready" if ready_to_serve else "not_ready"},
        status=200 if ready_to_serve else 503,
    )
