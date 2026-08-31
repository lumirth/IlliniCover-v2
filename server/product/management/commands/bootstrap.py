import json
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_datetime

from product.models import (
    DealFamily,
    HandbookPage,
    HistoricalDealFact,
    Submission,
    Venue,
)


def rows(name):
    with (settings.REPOSITORY_DIR / "data" / name).open() as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def timing(row):
    start, end, at = (
        row.get("timing_start_local"),
        row.get("timing_end_local"),
        row.get("timing_time_local"),
    )
    kind = row.get("timing_kind")
    if kind == "all_night":
        return "All night"
    if kind == "before_time" and at:
        return f"Before {at[:5]}"
    if kind == "after_time" and at:
        return f"After {at[:5]}"
    if kind == "between_times" and start and end:
        return f"{start[:5]}–{end[:5]}"
    return "While supplies last" if row.get("while_supplies_last") else ""


class Command(BaseCommand):
    help = "Load the canonical pre-alpha venue, cover, and deal data."

    @transaction.atomic
    def handle(self, **options):
        venues = {}
        for row in rows("venues.jsonl"):
            venue, _ = Venue.objects.update_or_create(
                slug=row["venue_slug"],
                defaults={
                    "name": row["display_name"],
                    "address": row.get("address", ""),
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude"),
                    "opened_year": row.get("opened_year"),
                    "is_active": row["active"],
                },
            )
            venues[venue.slug] = venue
        Venue.objects.exclude(slug__in=venues).update(is_active=False)

        cover_keys = set()
        for row in rows("covers.jsonl"):
            received = parse_datetime(row["received_at"])
            observed = parse_datetime(row["observed_at"])
            if received is None or observed is None:
                raise ValueError(f"invalid cover timestamp: {row['source_record_key']}")
            cover_keys.add(row["source_record_key"])
            Submission.objects.update_or_create(
                source_record_key=row["source_record_key"],
                defaults={
                    "kind": Submission.Kind.OBSERVATIONS,
                    "venue": venues[row["venue_slug"]],
                    "observed_at_client": observed,
                    "received_at_server": received,
                    "cover_price_cents": row["reported_price_cents"],
                    "cover_interaction": "historical",
                    "trust": {},
                },
            )
        Submission.objects.filter(source_record_key__isnull=False).exclude(
            source_record_key__in=cover_keys
        ).delete()

        deal_keys = set()
        for row in rows("deals.jsonl"):
            family, _ = DealFamily.objects.get_or_create(
                canonical_name=row["canonical_family"],
                category=row["category"],
            )
            deal_keys.add(row["source_record_key"])
            HistoricalDealFact.objects.update_or_create(
                source_record_key=row["source_record_key"],
                defaults={
                    "source": row["source_record_key"].split(":offer:", 1)[0],
                    "venue": venues[row["venue_slug"]],
                    "family": family,
                    "display_name": row["display_name"],
                    "price_kind": row["price_kind"],
                    "price_cents": row.get("price_amount_cents"),
                    "discount_percent": row.get("price_relative_percent"),
                    "unit": row.get("unit") or "",
                    "service_date_local": row["service_date"],
                    "timing_description": timing(row),
                    "while_supplies_last": row.get("while_supplies_last", False),
                },
            )
        HistoricalDealFact.objects.exclude(source_record_key__in=deal_keys).delete()
        DealFamily.objects.filter(facts__isnull=True).delete()
        if not venues or not cover_keys or not deal_keys:
            raise ValueError("canonical bootstrap data must not be empty")

        HandbookPage.objects.update_or_create(
            slug="about-cover",
            defaults={
                "title": "Understanding cover",
                "summary": "How IlliniCover estimates cover.",
                "body_markdown": (
                    "IlliniCover combines community reports with historical patterns. "
                    "A displayed estimate is not an official venue price."
                ),
                "published": True,
                "sort_order": 10,
            },
        )
        host = urlparse(settings.PUBLIC_API_ORIGIN).hostname
        if not host:
            raise ValueError("PUBLIC_API_ORIGIN must contain a hostname")
        Site.objects.update_or_create(pk=1, defaults={"domain": host, "name": "IlliniCover"})
        self.stdout.write(
            f"loaded {len(venues)} venues, {len(cover_keys)} covers, {len(deal_keys)} deals"
        )
