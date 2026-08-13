from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

from context.models import AdvertisedAdmission, SourceFetch
from covers.modeling import HistoricalModel, HistoricalModelConfig, HistoricalObservation
from covers.modeling.service_night import service_date_for
from covers.models import CoverModelRelease, CoverObservation
from deals.models import (
    DealAlias,
    DealDefinition,
    DealFamily,
    DealPrediction,
    DealPredictionRelease,
    HistoricalDealFact,
)
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime
from identity.models import InstallationActor
from submissions.models import Submission, SubmissionPrivateContext
from venues.models import Venue
from vibes.models import VibeObservation

FIXTURE_REVISION = "visual-acceptance-v1"
NAMESPACE = uuid.UUID("314d8a52-aa38-4c8f-b7db-2ace0fc34934")


def fixture_uuid(value: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, value)


class Command(BaseCommand):
    help = "Seed one disposable, deterministic local visual-acceptance profile."

    def add_arguments(self, parser):
        parser.add_argument(
            "--profile",
            required=True,
            choices=("empty", "cover-states", "historical", "deals-search"),
        )
        parser.add_argument("--at", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        self._guard()
        moment = parse_datetime(options["at"])
        if moment is None or moment.tzinfo is None:
            raise CommandError("--at must be an aware ISO 8601 timestamp")
        if Submission.objects.exists() or Venue.objects.exists():
            raise CommandError("visual acceptance database must be empty before seeding")

        profile = options["profile"]
        venues = self._venues()
        if profile == "cover-states":
            self._cover_states(venues, moment)
            self._deals(venues, moment)
            self._search_facts(venues, moment)
        elif profile == "historical":
            self._historical(venues, moment)
        elif profile == "deals-search":
            self._deals(venues, moment)
            self._search_facts(venues, moment)

        self.stdout.write(
            self.style.SUCCESS(
                f"seeded {FIXTURE_REVISION} profile={profile} at={moment.isoformat()}"
            )
        )

    def _guard(self):
        if not getattr(settings, "VISUAL_ACCEPTANCE", False) or not settings.DEBUG:
            raise CommandError("visual acceptance settings are required")
        if connection.vendor != "sqlite":
            raise CommandError("visual acceptance requires SQLite")
        expected_root = (settings.REPOSITORY_DIR / ".local" / "visual-acceptance").resolve()
        database = connection.settings_dict["NAME"].resolve()
        if database.parent != expected_root or database.suffix != ".sqlite3":
            raise CommandError("visual acceptance database path is outside the allowed root")

    def _venues(self) -> dict[str, Venue]:
        values = (
            ("live", "KAMS", "102 E Green St, Champaign, IL", 1933),
            ("mixed", "Joe's", "706 S 5th St, Champaign, IL", 1991),
            ("unconfirmed", "Red Lion", "211 E Green St, Champaign, IL", 2010),
            ("advertised", "Brothers", "613 E Green St, Champaign, IL", 2023),
            (
                "advertised-range",
                "Legends",
                "522 East Green Street",
                1998,
            ),
            ("unavailable", "Murphy's Pub", "604 East Green Street", 1969),
            (
                "overflow",
                "A Deliberately Very Long Venue Name for Layout Verification",
                "123 A Very Long Address Used Only for Local Visual Acceptance",
                2026,
            ),
        )
        return {
            slug: Venue.objects.create(
                id=fixture_uuid(f"venue:{slug}"),
                slug=slug,
                name=name,
                address=address,
                opened_year=year,
                sort_order=index,
            )
            for index, (slug, name, address, year) in enumerate(values)
        }

    def _cover_states(self, venues: dict[str, Venue], moment: datetime):
        self._cover_report(venues["live"], moment - timedelta(minutes=2), 1_000, "live-a")
        self._vibe_report(
            venues["live"],
            moment - timedelta(minutes=1),
            "vibe-only",
            vibes=(
                ("line_length", "medium"),
                ("line_speed", "normal"),
                ("crowd_level", "packed"),
            ),
        )
        for suffix, price in (("a", 500), ("b", 1_500)):
            self._cover_report(
                venues["mixed"], moment - timedelta(minutes=4), price, f"mixed-{suffix}"
            )
        self._cover_report(
            venues["unconfirmed"],
            moment - timedelta(minutes=6),
            2_000,
            "unconfirmed-a",
            snapshot={"rapidSpam": True},
        )
        for index in range(5):
            self._cover_report(
                venues["live"],
                moment - timedelta(minutes=8 + index),
                1_000,
                f"history-{index}",
                vibes=(
                    ("line_length", "short" if index < 3 else "medium"),
                    ("line_speed", "fast"),
                    ("crowd_level", "busy"),
                ),
            )
        # No current-night detail rows, but one older report inside the free
        # history window. This makes the More Reports route independently
        # fixture-testable instead of coupling it to tonight's preview.
        self._cover_report(
            venues["unavailable"],
            moment - timedelta(days=2),
            1_500,
            "older-history-only",
        )
        self._cover_report(venues["overflow"], moment - timedelta(minutes=3), 7_000, "overflow")
        source = SourceFetch.objects.create(
            id=fixture_uuid("source:advertised"),
            source_identifier="visual-acceptance",
            fetched_at=moment - timedelta(minutes=15),
            source_url="https://example.invalid/visual-acceptance",
            external_key="advertised",
            payload_hash="a" * 64,
            parser_version=FIXTURE_REVISION,
            status="succeeded",
        )
        AdvertisedAdmission.objects.create(
            venue=venues["advertised"],
            price_cents=1_500,
            starts_at=moment - timedelta(hours=2),
            ends_at=moment + timedelta(hours=2),
            is_unconditional=True,
            source_fetch=source,
        )
        for price_cents in (500, 1_500):
            AdvertisedAdmission.objects.create(
                venue=venues["advertised-range"],
                price_cents=price_cents,
                starts_at=moment - timedelta(hours=2),
                ends_at=moment + timedelta(hours=2),
                is_unconditional=True,
                source_fetch=source,
            )

    def _vibe_report(
        self,
        venue: Venue,
        observed_at: datetime,
        key: str,
        *,
        vibes: tuple[tuple[str, str], ...],
    ):
        actor = InstallationActor.objects.create(id=fixture_uuid(f"actor:{key}"))
        submission = Submission.objects.create(
            id=fixture_uuid(f"submission:{key}"),
            request_fingerprint=hashlib.sha256(key.encode()).hexdigest(),
            kind=Submission.Kind.OBSERVATIONS,
            venue=venue,
            observed_at_client=observed_at,
            received_at_server=observed_at + timedelta(seconds=5),
            time_quality=Submission.TimeQuality.PLAUSIBLE,
            vantage_point=Submission.VantagePoint.OUTSIDE,
            client_platform="ios",
            client_version="visual-acceptance",
            entry_point="visual_fixture",
        )
        SubmissionPrivateContext.objects.create(
            submission=submission,
            actor=actor,
            evidence_snapshot={"signedIn": False, "installationAgeDays": 45},
            location_permission="not_supplied",
        )
        VibeObservation.objects.bulk_create(
            [
                VibeObservation(submission=submission, dimension=dimension, value=value)
                for dimension, value in vibes
            ]
        )

    def _cover_report(
        self,
        venue: Venue,
        observed_at: datetime,
        price_cents: int,
        key: str,
        *,
        snapshot: dict | None = None,
        vibes: tuple[tuple[str, str], ...] = (),
    ):
        actor = InstallationActor.objects.create(id=fixture_uuid(f"actor:{key}"))
        submission = Submission.objects.create(
            id=fixture_uuid(f"submission:{key}"),
            request_fingerprint=hashlib.sha256(key.encode()).hexdigest(),
            kind=Submission.Kind.OBSERVATIONS,
            venue=venue,
            observed_at_client=observed_at,
            received_at_server=observed_at + timedelta(seconds=5),
            time_quality=Submission.TimeQuality.PLAUSIBLE,
            vantage_point=(
                Submission.VantagePoint.OUTSIDE
                if key.endswith(("0", "2", "4"))
                else Submission.VantagePoint.INSIDE
            ),
            client_platform="ios",
            client_version="visual-acceptance",
            entry_point="visual_fixture",
        )
        evidence = {"signedIn": False, "installationAgeDays": 45, **(snapshot or {})}
        SubmissionPrivateContext.objects.create(
            submission=submission,
            actor=actor,
            evidence_snapshot=evidence,
            location_permission="not_supplied",
        )
        CoverObservation.objects.create(
            submission=submission,
            reported_price_cents=price_cents,
            interaction_kind=CoverObservation.InteractionKind.DIRECT,
            independence_group_key=actor.id,
            admission_snapshot=evidence,
        )
        VibeObservation.objects.bulk_create(
            [
                VibeObservation(submission=submission, dimension=dimension, value=value)
                for dimension, value in vibes
            ]
        )

    def _historical(self, venues: dict[str, Venue], moment: datetime):
        rows = []
        parity_prices = (
            ("live", 1_000),
            ("mixed", 1_000),
            ("unconfirmed", 1_000),
            ("advertised", 500),
            ("overflow", 1_200),
        )
        for index, (venue_key, price) in enumerate(parity_prices):
            observed = moment - timedelta(days=7 * (index + 1))
            rows.append(
                HistoricalObservation(
                    observation_id=f"historical-{venue_key}",
                    venue_id=str(venues[venue_key].id),
                    observed_at=observed,
                    available_at=observed + timedelta(hours=1),
                    service_date=service_date_for(observed),
                    price_cents=price,
                )
            )
        model = HistoricalModel.fit(
            rows,
            HistoricalModelConfig(
                release_id="visual_historical",
                venue_pooling_strength=0,
            ),
        )
        CoverModelRelease.objects.create(
            id=fixture_uuid("cover-release:historical"),
            model_kind="historical",
            model_version="visual_historical",
            code_revision=FIXTURE_REVISION,
            training_data_revision=FIXTURE_REVISION,
            parameters_or_artifact=model.to_artifact(),
            evaluation_metrics={"fixture": True},
            is_authoritative=True,
            promoted_at=moment - timedelta(days=1),
        )

    def _deals(self, venues: dict[str, Venue], moment: datetime):
        shapes = (
            (
                "kams",
                "live",
                "White Claw",
                "single",
                300,
                None,
                "",
                "",
                False,
                False,
                "likely",
            ),
            (
                "joes",
                "mixed",
                "Michelob Ultra",
                "single",
                500,
                None,
                "",
                "All night",
                True,
                False,
                "likely",
            ),
            (
                "red-bombs",
                "unconfirmed",
                "Bombs",
                "single",
                100,
                None,
                "",
                "9–9:59 PM",
                True,
                False,
                "likely",
            ),
            (
                "brothers-wells",
                "advertised",
                "Wells",
                "single",
                100,
                None,
                "",
                "",
                False,
                False,
                "likely",
            ),
            (
                "brothers-busch",
                "advertised",
                "Busch Light",
                "single",
                200,
                None,
                "can",
                "",
                False,
                False,
                "likely",
            ),
            (
                "brothers-third",
                "advertised",
                "Big Cups",
                "single",
                500,
                None,
                "cup",
                "",
                False,
                False,
                "likely",
            ),
            (
                "range",
                "advertised-range",
                "Domestic Bottles",
                "range",
                None,
                None,
                "bottle",
                "Before 10 PM",
                True,
                False,
                "current",
            ),
            (
                "percent",
                "advertised-range",
                "All Appetizers",
                "percent_off",
                None,
                25,
                "plate",
                "After 9 PM",
                True,
                False,
                "advertised",
            ),
            (
                "unknown",
                "overflow",
                "Mystery Drink Special with an Intentionally Long Name",
                "unknown",
                None,
                None,
                "",
                "",
                False,
                False,
                "unknown",
            ),
            (
                "soldout",
                "overflow",
                "Orange Blue Guys",
                "single",
                300,
                None,
                "cup",
                "",
                True,
                True,
                "current",
            ),
            (
                "between",
                "overflow",
                "Draft Beer",
                "single",
                400,
                None,
                "draft",
                "7 PM–10 PM",
                True,
                False,
                "likely",
            ),
        )
        definitions: dict[str, DealDefinition] = {}
        for shape in shapes:
            (
                key,
                venue_key,
                name,
                kind,
                cents,
                percent,
                unit,
                timing,
                known,
                soldout,
                status,
            ) = shape
            definitions[key] = DealDefinition.objects.create(
                id=fixture_uuid(f"deal:{key}"),
                venue=venues[venue_key],
                display_name=name,
                category="food" if key == "percent" else "drink",
                price_kind=kind,
                price_cents=cents,
                price_low_cents=300 if kind == "range" else None,
                price_high_cents=500 if kind == "range" else None,
                discount_percent=Decimal(percent) if percent is not None else None,
                unit=unit,
                timing_description=timing,
                timing_known=known,
                while_supplies_last=soldout,
                status=status,
            )
            DealDefinition.objects.filter(pk=definitions[key].pk).update(
                created_at=moment - timedelta(days=7)
            )

        release = DealPredictionRelease.objects.create(
            id=fixture_uuid("deal-release:ranked"),
            predictor_version="visual_ranked_v1",
            code_revision=FIXTURE_REVISION,
            training_data_revision=FIXTURE_REVISION,
            parameters={"fixture": True},
            evaluation_metrics={"fixture": True},
            is_authoritative=True,
            promoted_at=moment,
        )
        service_date = service_date_for(moment)
        # Each venue owns its rank namespace. Brothers deliberately uses the
        # established non-alphabetic v1 ordering so LiveAPI acceptance proves
        # the persisted predictor rank rather than the definition fallback.
        rank_by_key = {
            "kams": 1,
            "joes": 1,
            "red-bombs": 1,
            "brothers-wells": 1,
            "brothers-busch": 2,
            "brothers-third": 3,
            "range": 1,
            "percent": 2,
            "unknown": 1,
            "soldout": 2,
            "between": 3,
        }
        for key, definition in definitions.items():
            prediction = DealPrediction.objects.create(
                id=fixture_uuid(f"prediction:{key}"),
                release=release,
                venue=definition.venue,
                deal_definition=definition,
                service_date_local=service_date,
                support_nights=max(1, 8 - rank_by_key[key]),
                comparable_nights=8,
                latest_evidence_date=service_date - timedelta(days=7),
                rank=rank_by_key[key],
                status=definition.status,
            )
            DealPrediction.objects.filter(pk=prediction.pk).update(
                created_at=moment - timedelta(minutes=rank_by_key[key])
            )

    def _search_facts(self, venues: dict[str, Venue], moment: datetime):
        family = DealFamily.objects.create(
            id=fixture_uuid("family:wells"), canonical_name="Wells", category="drink"
        )
        DealAlias.objects.create(family=family, alias="Happy Hour Rail Drinks")
        variants = (
            ("three", "Wells", 300, "cup", "unknown", None, "live"),
            ("five", "Wells", 500, "pitcher", "all_night", None, "live"),
            (
                "before",
                "Wells Before Ten",
                400,
                "drink",
                "before_time",
                time(22, 0),
                "live",
            ),
            (
                "global",
                "Wells After Nine",
                600,
                "bottle",
                "after_time",
                time(21, 0),
                "advertised",
            ),
            (
                "long",
                "An Intentionally Very Long Happy Hour Rail Drink Name for Overflow",
                700,
                "32 ounce souvenir pitcher",
                "all_night",
                None,
                "unconfirmed",
            ),
            (
                "late",
                "Late Night Wells",
                200,
                "",
                "after_time",
                time(23, 0),
                "mixed",
            ),
        )
        for index, (
            key,
            name,
            cents,
            unit,
            timing_kind,
            timing_time,
            venue_key,
        ) in enumerate(variants):
            HistoricalDealFact.objects.create(
                id=fixture_uuid(f"fact:{key}"),
                source_record_key=f"visual:{key}",
                source_dataset=FIXTURE_REVISION,
                venue=venues[venue_key],
                family=family,
                display_name=name,
                category="drink",
                price_kind="single",
                price_cents=cents,
                unit=unit,
                service_date_local=(moment - timedelta(days=index + 1)).date(),
                timing_kind=timing_kind,
                timing_time_local=timing_time,
                source_post_key=f"visual:{key}",
                source_payload_hash="b" * 64,
            )
