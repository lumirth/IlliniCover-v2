import json
import logging
import uuid
from datetime import timedelta

import pytest
from billing.models import AccountEntitlement
from config.logging import JsonFormatter
from context.models import AdvertisedAdmission, SourceFetch
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models.signals import post_save
from django.test import Client, override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from identity.models import Account
from identity.tokens import issue_session_token
from operations.models import JobRun
from submissions.models import Submission
from venues.models import Venue
from vibes.models import VibeObservation

from covers.modeling import HistoricalModel, HistoricalModelConfig, HistoricalObservation
from covers.models import (
    CoverDecision,
    CoverModelRelease,
    CoverObservation,
    CoverTrainingRevision,
)
from covers.releases import (
    ChallengerEvaluationError,
    completed_training_selection,
    promote_release,
    train_completed_night_challenger,
)
from covers.services import (
    FREE_HISTORY_REPORT_LIMIT,
    authoritative_release_at,
    cover_board,
    current_decision,
    service_date_for,
)


def create_public_cover_report(venue: Venue, observed_at, price_cents: int) -> Submission:
    submission = Submission.objects.create(
        id=uuid.uuid4(),
        request_fingerprint=uuid.uuid4().hex * 2,
        kind=Submission.Kind.OBSERVATIONS,
        venue=venue,
        observed_at_client=observed_at,
        received_at_server=observed_at + timedelta(seconds=10),
        time_quality=Submission.TimeQuality.PLAUSIBLE,
    )
    CoverObservation.objects.create(
        submission=submission,
        reported_price_cents=price_cents,
        interaction_kind=CoverObservation.InteractionKind.DIRECT,
        admission_snapshot={"resolverVersion": "cover_trust_v1"},
    )
    return submission


def create_authoritative_cover_release(version: str) -> CoverModelRelease:
    model = HistoricalModel.fit([], HistoricalModelConfig(release_id=version))
    return CoverModelRelease.objects.create(
        model_kind="historical",
        model_version=version,
        code_revision="test",
        training_data_revision=f"{version}-training",
        parameters_or_artifact=model.to_artifact(),
        is_authoritative=True,
    )


def authenticated_premium_client() -> tuple[Client, Account]:
    account = Account.objects.create_user("premium@example.com")
    AccountEntitlement.objects.create(account=account, is_active=True)
    session = SessionStore()
    session[SESSION_KEY] = str(account.pk)
    session.save()
    token = issue_session_token(session)
    return Client(headers={"X-Session-Token": token}), account


@pytest.mark.django_db
def test_time_machine_runs_reconstruction_and_persists_decision_receipt():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client, _account = authenticated_premium_client()
    target = timezone.now() + timedelta(hours=2)

    response = client.get(
        f"/api/v2/venues/{venue.slug}/cover/time-machine", {"target_time": target.isoformat()}
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    effective_target = target.replace(second=0, microsecond=0)
    assert parse_datetime(response.json()["targetTime"]) == effective_target
    decision = CoverDecision.objects.get(pk=response.json()["cover"]["decisionId"])
    assert parse_datetime(response.json()["knowledgeCutoff"]) == decision.knowledge_cutoff
    assert response.json()["mode"] == "future"
    assert response.json()["cover"]["decisionId"]


@pytest.mark.django_db
def test_time_machine_server_owns_past_current_and_future_mode_boundaries():
    venue = Venue.objects.create(slug="modes", name="Modes")
    client, _account = authenticated_premium_client()
    cutoff = timezone.now().replace(second=30, microsecond=0)

    with override_settings(VISUAL_ACCEPTANCE=True, VISUAL_ACCEPTANCE_NOW=cutoff):
        cases = (
            (-61, "past"),
            (-60, "current"),
            (0, "current"),
            (60, "current"),
            (61, "future"),
        )
        modes = []
        for seconds, expected in cases:
            response = client.get(
                f"/api/v2/venues/{venue.slug}/cover/time-machine",
                {"target_time": (cutoff + timedelta(seconds=seconds)).isoformat()},
            )
            assert response.status_code == 200
            assert response.json()["mode"] == expected
            modes.append(response.json()["mode"])

    assert modes == ["past", "current", "current", "current", "future"]


@pytest.mark.django_db
def test_time_machine_reports_the_exact_minute_cutoff_used_for_evidence():
    venue = Venue.objects.create(slug="honest-cutoff", name="Honest Cutoff")
    client, _account = authenticated_premium_client()
    real_clock = timezone.now().replace(second=50, microsecond=0)
    stable_cutoff = real_clock.replace(second=0)
    create_public_cover_report(
        venue,
        stable_cutoff + timedelta(seconds=20),
        1_500,
    )

    with override_settings(VISUAL_ACCEPTANCE=True, VISUAL_ACCEPTANCE_NOW=real_clock):
        response = client.get(
            f"/api/v2/venues/{venue.slug}/cover/time-machine",
            {"target_time": real_clock.isoformat()},
        )

    assert response.status_code == 200
    decision = CoverDecision.objects.get(pk=response.json()["cover"]["decisionId"])
    assert parse_datetime(response.json()["knowledgeCutoff"]) == stable_cutoff
    assert decision.knowledge_cutoff == stable_cutoff
    assert response.json()["cover"]["source"] == "unavailable"


@pytest.mark.django_db
def test_time_machine_reuses_minute_receipt_and_enforces_target_window_and_rate_limit():
    venue = Venue.objects.create(slug="bounded", name="Bounded")
    client, _account = authenticated_premium_client()
    cutoff = timezone.now().replace(second=30, microsecond=0)
    endpoint = f"/api/v2/venues/{venue.slug}/cover/time-machine"

    with override_settings(
        VISUAL_ACCEPTANCE=True,
        VISUAL_ACCEPTANCE_NOW=cutoff,
        TIME_MACHINE_ACCOUNT_RATE_LIMIT=(2, 3_600),
        TIME_MACHINE_NETWORK_RATE_LIMIT=(10, 3_600),
    ):
        first = client.get(endpoint, {"target_time": cutoff.isoformat()})
        second = client.get(endpoint, {"target_time": cutoff.isoformat()})
        too_old = client.get(
            endpoint,
            {"target_time": (cutoff - timedelta(days=3_651)).isoformat()},
        )
        too_far = client.get(
            endpoint,
            {"target_time": (cutoff + timedelta(days=366)).isoformat()},
        )
        limited = client.get(endpoint, {"target_time": cutoff.isoformat()})

    assert first.status_code == second.status_code == 200
    assert first.json()["cover"]["decisionId"] == second.json()["cover"]["decisionId"]
    assert CoverDecision.objects.count() == 1
    assert too_old.status_code == too_far.status_code == 422
    assert too_old.json()["code"] == too_far.json()["code"] == "unsupported_target_time"
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"


@pytest.mark.django_db
def test_current_time_machine_reuses_the_exact_board_decision_receipt():
    venue = Venue.objects.create(slug="shared-current", name="Shared Current")
    client, _account = authenticated_premium_client()
    cutoff = timezone.now().replace(second=0, microsecond=0)

    with override_settings(VISUAL_ACCEPTANCE=True, VISUAL_ACCEPTANCE_NOW=cutoff):
        board = client.get("/api/v2/cover")
        time_machine = client.get(
            f"/api/v2/venues/{venue.slug}/cover/time-machine",
            {"target_time": cutoff.isoformat()},
        )

    assert board.status_code == time_machine.status_code == 200
    board_decision = next(
        item["cover"] for item in board.json()["venues"] if item["venue"]["slug"] == venue.slug
    )
    assert board_decision["decisionId"] == time_machine.json()["cover"]["decisionId"]
    assert (
        CoverDecision.objects.filter(
            venue=venue,
            target_time=cutoff,
            knowledge_cutoff=cutoff,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_report_history_applies_free_and_premium_windows_without_expanding_report_data():
    venue = Venue.objects.create(slug="history", name="History")
    now = timezone.now()
    recent = create_public_cover_report(venue, now - timedelta(days=6), 1_000)
    older = create_public_cover_report(venue, now - timedelta(days=30), 1_500)

    free = Client().get(f"/api/v2/venues/{venue.slug}/cover/history")
    premium_client, _account = authenticated_premium_client()
    premium = premium_client.get(f"/api/v2/venues/{venue.slug}/cover/history")

    assert free.status_code == 200
    assert "X-Session-Token" in free.headers["Vary"]
    assert free.json()["accessTier"] == "limited"
    assert free.json()["hasMore"] is False
    assert [report["submissionId"] for report in free.json()["reports"]] == [str(recent.pk)]
    assert premium.status_code == 200
    assert premium.headers["Cache-Control"] == "no-store"
    assert "X-Session-Token" in premium.headers["Vary"]
    assert premium.json()["accessTier"] == "extended"
    assert [report["submissionId"] for report in premium.json()["reports"]] == [
        str(recent.pk),
        str(older.pk),
    ]
    assert "latitude" not in premium.json()["reports"][0]
    assert "account" not in premium.json()["reports"][0]


@pytest.mark.django_db
def test_free_report_history_is_bounded_and_reports_truncation():
    venue = Venue.objects.create(slug="busy-history", name="Busy History")
    now = timezone.now()
    for index in range(FREE_HISTORY_REPORT_LIMIT + 1):
        observed_at = now - timedelta(seconds=index + 1)
        submission = Submission.objects.create(
            id=uuid.uuid4(),
            request_fingerprint=uuid.uuid4().hex * 2,
            kind=Submission.Kind.OBSERVATIONS,
            venue=venue,
            observed_at_client=observed_at,
            received_at_server=observed_at + timedelta(milliseconds=100),
            time_quality=Submission.TimeQuality.PLAUSIBLE,
        )
        VibeObservation.objects.create(
            submission=submission,
            dimension=VibeObservation.Dimension.LINE_LENGTH,
            value="medium",
        )

    response = Client().get(f"/api/v2/venues/{venue.slug}/cover/history")

    assert response.status_code == 200
    assert response.json()["accessTier"] == "limited"
    assert response.json()["hasMore"] is True
    assert len(response.json()["reports"]) == FREE_HISTORY_REPORT_LIMIT


@pytest.mark.django_db
def test_venue_cover_request_log_correlates_client_request_and_served_decision(caplog):
    venue = Venue.objects.create(slug="kams", name="KAMS")
    request_id = str(uuid.uuid4())

    with caplog.at_level(logging.INFO, logger="illinicover.request"):
        response = Client(headers={"X-Request-ID": request_id}).get(
            f"/api/v2/venues/{venue.slug}/cover"
        )

    assert response.status_code == 200
    decision_id = response.json()["cover"]["decisionId"]
    receipt = next(
        record
        for record in caplog.records
        if record.name == "illinicover.request" and record.msg == "request.completed"
    )
    assert receipt.request_id == request_id
    assert receipt.decision_id == decision_id


@pytest.mark.django_db
def test_cover_board_logs_one_privacy_safe_receipt_per_served_decision(caplog):
    Venue.objects.create(slug="kams", name="KAMS")
    Venue.objects.create(slug="legends", name="Legends")
    request_id = str(uuid.uuid4())

    with caplog.at_level(logging.INFO, logger="illinicover.cover"):
        response = Client(headers={"X-Request-ID": request_id}).get("/api/v2/cover")

    expected = {
        card["cover"]["decisionId"]
        for card in response.json()["venues"]
        if card["cover"]["decisionId"] is not None
    }
    receipts = [
        record
        for record in caplog.records
        if record.name == "illinicover.cover" and record.msg == "cover.decision_served"
    ]

    assert response.status_code == 200
    assert {receipt.decision_id for receipt in receipts} == expected
    assert all(receipt.request_id == request_id for receipt in receipts)
    assert all(receipt.endpoint == "/api/v2/cover" for receipt in receipts)


@pytest.mark.django_db
def test_non_uuid_client_request_id_is_replaced_before_response_and_logging(caplog):
    with caplog.at_level(logging.INFO, logger="illinicover.request"):
        response = Client(headers={"X-Request-ID": "stable-user-pseudonym"}).get("/health/live")

    response_request_id = response.headers["X-Request-ID"]
    receipt = next(
        record
        for record in caplog.records
        if record.name == "illinicover.request" and record.msg == "request.completed"
    )

    assert uuid.UUID(response_request_id).version == 4
    assert response.status_code == 200
    assert response_request_id != "stable-user-pseudonym"
    assert receipt.request_id == response_request_id


@pytest.mark.django_db
def test_unmatched_short_user_path_is_generalized_before_logging(caplog):
    with caplog.at_level(logging.INFO, logger="illinicover.request"):
        response = Client().get("/not-a-route/lu@example.com")

    receipt = next(
        record
        for record in caplog.records
        if record.name == "illinicover.request" and record.msg == "request.completed"
    )
    payload = json.loads(JsonFormatter().format(receipt))

    assert response.status_code == 404
    assert receipt.endpoint == "/unmatched"
    assert payload["endpoint"] == "/unmatched"
    assert "lu@example.com" not in json.dumps(payload)


@pytest.mark.django_db
def test_retired_model_release_cannot_be_repromoted_and_lose_its_authority_interval():
    first = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="one",
        code_revision="one",
        training_data_revision="one",
        parameters_or_artifact={"artifact_schema": "one"},
        is_authoritative=True,
    )
    second = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="two",
        code_revision="two",
        training_data_revision="two",
        parameters_or_artifact={"artifact_schema": "two"},
    )

    promote_release(second)
    first.refresh_from_db()
    original_promotion = first.promoted_at
    original_retirement = first.retired_at

    with pytest.raises(ChallengerEvaluationError, match="retired"):
        promote_release(first)

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.is_authoritative is False
    assert first.promoted_at == original_promotion
    assert first.retired_at == original_retirement
    assert second.is_authoritative is True
    assert first.parameters_or_artifact == {"artifact_schema": "one"}


@pytest.mark.django_db
def test_authoritative_release_lookup_respects_promotion_history_at_the_cutoff():
    cutoff = timezone.now()
    first = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="chronology-one",
        code_revision="one",
        training_data_revision="one",
        is_authoritative=True,
    )
    second = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="chronology-two",
        code_revision="two",
        training_data_revision="two",
    )
    promotion = cutoff + timedelta(hours=1)
    CoverModelRelease.objects.filter(pk=first.pk).update(
        created_at=cutoff - timedelta(days=2),
        is_authoritative=False,
        retired_at=promotion,
    )
    CoverModelRelease.objects.filter(pk=second.pk).update(
        created_at=cutoff - timedelta(days=1),
        is_authoritative=True,
        promoted_at=promotion,
    )

    assert authoritative_release_at(cutoff) == first
    assert authoritative_release_at(promotion + timedelta(seconds=1)) == second


@pytest.mark.django_db
def test_authoritative_release_lookup_never_selects_a_retired_shadow_challenger():
    cutoff = timezone.now()
    authority = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="legacy-authority",
        code_revision="authority-code",
        training_data_revision="authority-training",
        is_authoritative=True,
    )
    shadow = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="never-authoritative-shadow",
        code_revision="shadow-code",
        training_data_revision="shadow-training",
    )
    CoverModelRelease.objects.filter(pk=authority.pk).update(
        created_at=cutoff - timedelta(days=2),
        is_authoritative=False,
        retired_at=cutoff + timedelta(hours=1),
    )
    CoverModelRelease.objects.filter(pk=shadow.pk).update(
        created_at=cutoff - timedelta(days=1),
        retired_at=cutoff + timedelta(hours=2),
    )

    assert authoritative_release_at(cutoff) == authority


@pytest.mark.django_db
def test_promote_cover_model_rejects_free_form_evaluation_flags_without_receipt():
    revision = CoverTrainingRevision.objects.create(
        data_revision="command-training",
        knowledge_cutoff=timezone.now(),
        service_nights=1,
        observations_seen=1,
        observations_admitted=1,
    )
    model = HistoricalModel.fit([], HistoricalModelConfig(release_id="command-model"))
    release = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="command-model",
        code_revision="test",
        training_data_revision=revision.data_revision,
        parameters_or_artifact=model.to_artifact(),
        evaluation_metrics={
            "promotionEligible": True,
            "evaluationProtocol": "chronological_holdout",
            "challengerWon": True,
        },
    )

    with pytest.raises(CommandError, match="evaluation receipt"):
        call_command("promote_cover_model", str(release.pk), verbosity=0)

    release.refresh_from_db()
    assert release.is_authoritative is False


@pytest.mark.django_db
def test_promote_cover_model_rejects_unscored_shadow_challenger():
    revision = CoverTrainingRevision.objects.create(
        data_revision="pending-training",
        knowledge_cutoff=timezone.now(),
        service_nights=1,
        observations_seen=1,
        observations_admitted=1,
    )
    model = HistoricalModel.fit([], HistoricalModelConfig(release_id="pending-model"))
    release = CoverModelRelease.objects.create(
        model_kind="historical_challenger",
        model_version="pending-model",
        code_revision="test",
        training_data_revision=revision.data_revision,
        parameters_or_artifact=model.to_artifact(),
        evaluation_metrics={"status": "shadow_pending"},
    )

    with pytest.raises(CommandError, match="chronological winning evaluation receipt"):
        call_command("promote_cover_model", str(release.pk), verbosity=0)

    release.refresh_from_db()
    assert release.is_authoritative is False


@pytest.mark.django_db
def test_board_resolves_historical_answer_from_authoritative_release_without_live_reports():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    now = timezone.now()
    observed = now - timedelta(days=7)
    model = HistoricalModel.fit(
        [
            HistoricalObservation(
                observation_id="historical-1",
                venue_id=str(venue.id),
                observed_at=observed,
                available_at=observed + timedelta(minutes=5),
                service_date=service_date_for(observed),
                price_cents=1500,
            )
        ],
        HistoricalModelConfig(release_id="test-authoritative"),
    )
    release = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="test-authoritative",
        code_revision="test",
        training_data_revision="test-data",
        parameters_or_artifact=model.to_artifact(),
        is_authoritative=True,
    )

    response = Client().get("/api/v2/cover")

    assert response.status_code == 200
    cover = response.json()["venues"][0]["cover"]
    assert cover["source"] == "historical"
    assert cover["price"]["amountCents"] == 1500
    assert CoverDecision.objects.get(pk=cover["decisionId"]).model_release == release


@pytest.mark.django_db
def test_board_does_not_use_or_advertise_a_model_release_from_after_the_cutoff():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    now = timezone.now()
    model = HistoricalModel.fit(
        [
            HistoricalObservation(
                observation_id="future-release-row",
                venue_id=str(venue.id),
                observed_at=now - timedelta(days=7),
                available_at=now - timedelta(days=7) + timedelta(minutes=5),
                service_date=service_date_for(now - timedelta(days=7)),
                price_cents=1_500,
            )
        ],
        HistoricalModelConfig(release_id="future-release"),
    )
    release = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="future-release",
        code_revision="test",
        training_data_revision="future-data",
        parameters_or_artifact=model.to_artifact(),
        is_authoritative=True,
    )
    CoverModelRelease.objects.filter(pk=release.pk).update(
        created_at=now - timedelta(days=1),
        promoted_at=now + timedelta(minutes=1),
    )

    card = cover_board(now=now)["venues"][0]

    assert card["cover"]["source"] == "unavailable"
    assert card["latest_activity_at"] is None
    assert CoverDecision.objects.get(pk=card["cover"]["decision_id"]).model_release is None


@pytest.mark.django_db
def test_public_reads_reuse_one_receipt_while_served_state_is_unchanged():
    Venue.objects.create(slug="kams", name="KAMS")
    now = timezone.now().replace(second=1, microsecond=0)

    first = cover_board(now=now)
    later = cover_board(now=now + timedelta(hours=1))

    assert first["generated_at"] != later["generated_at"]
    assert first["venues"][0]["cover"]["decision_id"] == later["venues"][0]["cover"]["decision_id"]
    assert CoverDecision.objects.count() == 1
    assert CoverDecision.objects.get().served_state_key


@pytest.mark.django_db
def test_time_machine_receipt_cannot_be_selected_as_current_live_state():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    now = timezone.now()
    CoverDecision.objects.create(
        venue=venue,
        target_time=now - timedelta(minutes=5),
        knowledge_cutoff=now,
        result_price_kind="single",
        result_price_cents=9900,
        source="live",
        status="current",
        evidence_revision="resolution:time-machine-only",
        resolver_version="test",
    )

    assert current_decision(venue, now) is None
    cover = Client().get("/api/v2/cover").json()["venues"][0]["cover"]
    assert cover["source"] == "unavailable"


@pytest.mark.django_db
def test_board_interprets_only_current_unconditional_advertised_admission():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    now = timezone.now()
    source = SourceFetch.objects.create(
        source_identifier="venue-published-admission",
        fetched_at=now - timedelta(seconds=20),
        source_url="https://example.invalid/kams",
        external_key="kams-current",
        payload_hash="a" * 64,
        parser_version="test-v1",
        status="succeeded",
    )
    AdvertisedAdmission.objects.create(
        venue=venue,
        price_cents=2_000,
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=1),
        is_unconditional=True,
        source_fetch=source,
    )
    AdvertisedAdmission.objects.create(
        venue=venue,
        price_cents=500,
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=1),
        qualification="21+ only",
        is_unconditional=True,
        source_fetch=source,
    )

    response = Client().get("/api/v2/cover")

    assert response.status_code == 200
    cover = response.json()["venues"][0]["cover"]
    assert cover["source"] == "advertised"
    assert cover["status"] == "advertised"
    assert cover["price"]["amountCents"] == 2_000
    decision = CoverDecision.objects.get(pk=cover["decisionId"])
    assert decision.same_night_adjustment_summary["evidenceIds"] == [
        f"advertised:{AdvertisedAdmission.objects.get(price_cents=2_000).id}"
    ]


@pytest.mark.django_db
def test_time_machine_requires_an_explicit_timezone():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client, _account = authenticated_premium_client()

    response = client.get(
        f"/api/v2/venues/{venue.slug}/cover/time-machine",
        {"target_time": "2026-08-12T21:00:00"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "timezone_required"


@pytest.mark.django_db
def test_expired_premium_mirror_cannot_authorize_time_machine():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client, account = authenticated_premium_client()
    AccountEntitlement.objects.filter(account=account).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    response = client.get(
        f"/api/v2/venues/{venue.slug}/cover/time-machine",
        {"target_time": timezone.now().isoformat()},
    )
    entitlements = client.get("/api/v2/me/entitlements")

    assert response.status_code == 403
    assert response.json()["code"] == "premium_required"
    assert response.json()["message"] == "IlliniCover Blue is required for Time Machine."
    assert entitlements.status_code == 200
    assert entitlements.json()["entitlements"][0]["isActive"] is False


@pytest.mark.django_db
def test_completed_night_training_creates_non_authoritative_reproducible_challenger():
    baseline = create_authoritative_cover_release("training-baseline")
    venue = Venue.objects.create(slug="kams", name="KAMS")
    observed = timezone.now() - timedelta(days=2)
    submission = Submission.objects.create(
        id=uuid.uuid4(),
        request_fingerprint="a" * 64,
        kind="observations",
        venue=venue,
        observed_at_client=observed,
        received_at_server=observed + timedelta(minutes=1),
        time_quality="plausible",
    )
    CoverObservation.objects.create(
        submission=submission,
        reported_price_cents=1500,
        interaction_kind="direct",
        admission_snapshot={"resolverVersion": "cover_trust_v1"},
    )

    release = train_completed_night_challenger(knowledge_cutoff=timezone.now())

    assert release is not None
    assert release.is_authoritative is False
    assert release.parameters_or_artifact["artifact_schema"] == "cover_historical_kernel_v1"
    assert release.evaluation_metrics["promotion"] == "explicit_only"
    assert release.evaluation_metrics["baselineReleaseId"] == str(baseline.id)


@pytest.mark.django_db
def test_same_training_rows_under_new_code_create_a_new_challenger_identity():
    baseline = create_authoritative_cover_release("code-identity-baseline")
    venue = Venue.objects.create(slug="code-identity", name="Code Identity")
    cutoff = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
    create_public_cover_report(venue, cutoff - timedelta(days=2), 1_500)

    with override_settings(CODE_REVISION="src-first"):
        first = train_completed_night_challenger(knowledge_cutoff=cutoff)
    with override_settings(CODE_REVISION="src-second"):
        second = train_completed_night_challenger(knowledge_cutoff=cutoff)

    assert first is not None
    assert second is not None
    assert second.id != first.id
    assert second.code_revision == "src-second"
    assert second.training_data_revision == first.training_data_revision
    assert second.evaluation_metrics["baselineReleaseId"] == str(baseline.id)
    first.refresh_from_db()
    assert first.retired_at is not None


@pytest.mark.django_db
def test_same_training_rows_against_a_new_incumbent_create_a_new_challenger_identity():
    first_baseline = create_authoritative_cover_release("first-identity-baseline")
    venue = Venue.objects.create(slug="baseline-identity", name="Baseline Identity")
    cutoff = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
    create_public_cover_report(venue, cutoff - timedelta(days=2), 1_500)

    with override_settings(CODE_REVISION="src-stable"):
        first = train_completed_night_challenger(knowledge_cutoff=cutoff)
    replacement_model = HistoricalModel.fit(
        [], HistoricalModelConfig(release_id="replacement-identity-baseline")
    )
    replacement = CoverModelRelease.objects.create(
        model_kind="historical",
        model_version="replacement-identity-baseline",
        code_revision="replacement-code",
        training_data_revision="replacement-training",
        parameters_or_artifact=replacement_model.to_artifact(),
    )
    promote_release(replacement)

    with override_settings(CODE_REVISION="src-stable"):
        second = train_completed_night_challenger(knowledge_cutoff=cutoff)

    assert first is not None
    assert second is not None
    assert second.id != first.id
    assert second.training_data_revision == first.training_data_revision
    assert first.evaluation_metrics["baselineReleaseId"] == str(first_baseline.id)
    assert second.evaluation_metrics["baselineReleaseId"] == str(replacement.id)
    first.refresh_from_db()
    assert first.retired_at is not None


@pytest.mark.django_db
def test_existing_challenger_identity_fails_closed_if_its_model_payload_mismatches():
    create_authoritative_cover_release("mismatch-identity-baseline")
    venue = Venue.objects.create(slug="identity-mismatch", name="Identity Mismatch")
    cutoff = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
    create_public_cover_report(venue, cutoff - timedelta(days=2), 1_500)

    with override_settings(CODE_REVISION="src-stable"):
        release = train_completed_night_challenger(knowledge_cutoff=cutoff)
    assert release is not None
    mismatched_artifact = dict(release.parameters_or_artifact)
    mismatched_config = dict(mismatched_artifact["config"])
    mismatched_config["high_cover_threshold_cents"] = 9_999
    mismatched_artifact["config"] = mismatched_config
    CoverModelRelease.objects.filter(pk=release.pk).update(
        parameters_or_artifact=mismatched_artifact
    )

    with override_settings(CODE_REVISION="src-stable"):
        with pytest.raises(ChallengerEvaluationError, match="identity"):
            train_completed_night_challenger(knowledge_cutoff=cutoff)


@pytest.mark.django_db
def test_new_completed_night_challenger_retires_the_superseded_challenger():
    baseline = create_authoritative_cover_release("retirement-baseline")
    venue = Venue.objects.create(slug="challenger-retirement", name="Challenger Retirement")
    second_cutoff = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
    first_cutoff = second_cutoff - timedelta(days=2)
    create_public_cover_report(venue, second_cutoff - timedelta(days=4), 1_000)

    first = train_completed_night_challenger(knowledge_cutoff=first_cutoff)
    assert first is not None
    create_public_cover_report(venue, second_cutoff - timedelta(days=1), 1_500)

    second = train_completed_night_challenger(knowledge_cutoff=second_cutoff)

    assert second is not None
    assert second.id != first.id
    first.refresh_from_db()
    baseline.refresh_from_db()
    assert first.retired_at is not None
    assert second.retired_at is None
    assert baseline.is_authoritative is True
    assert list(
        CoverModelRelease.objects.filter(
            model_kind="historical_challenger",
            promoted_at__isnull=True,
            retired_at__isnull=True,
        ).values_list("id", flat=True)
    ) == [second.id]


@pytest.mark.django_db
def test_challenger_fits_the_exact_rows_captured_by_its_training_revision():
    create_authoritative_cover_release("captured-selection-baseline")
    venue = Venue.objects.create(slug="captured-selection", name="Captured Selection")
    cutoff = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
    first = create_public_cover_report(venue, cutoff - timedelta(days=2), 1_000)
    inserted_after_capture: list[Submission] = []

    def insert_eligible_row_after_revision_is_named(sender, instance, created, **_kwargs):
        if (
            created
            and instance.data_revision.startswith("production:")
            and not inserted_after_capture
        ):
            inserted_after_capture.append(
                create_public_cover_report(venue, cutoff - timedelta(days=1), 1_500)
            )

    post_save.connect(
        insert_eligible_row_after_revision_is_named,
        sender=CoverTrainingRevision,
        dispatch_uid="test-captured-cover-training-selection",
        weak=False,
    )
    try:
        call_command("refresh_cover_models", verbosity=0)
    finally:
        post_save.disconnect(
            sender=CoverTrainingRevision,
            dispatch_uid="test-captured-cover-training-selection",
        )

    assert len(inserted_after_capture) == 1
    release = CoverModelRelease.objects.get(model_kind="historical_challenger")
    revision = CoverTrainingRevision.objects.get(data_revision=release.training_data_revision)
    assert (
        JobRun.objects.get(name="refresh_cover_models").result_summary["dataRevision"]
        == revision.data_revision
    )
    assert revision.observations_admitted == 1
    assert [row["observation_id"] for row in release.parameters_or_artifact["observations"]] == [
        str(first.id)
    ]


@pytest.mark.django_db
def test_training_snapshot_and_artifact_share_actor_dedup_echo_and_weight_selection():
    baseline = create_authoritative_cover_release("selection-baseline")
    venue = Venue.objects.create(slug="training", name="Training")
    observed = timezone.now() - timedelta(days=2)
    actor_key = uuid.uuid4()

    def observation(minutes, price, key, **kwargs):
        moment = observed + timedelta(minutes=minutes)
        submission = Submission.objects.create(
            id=uuid.uuid4(),
            request_fingerprint=uuid.uuid4().hex * 2,
            kind="observations",
            venue=venue,
            observed_at_client=moment,
            received_at_server=moment + timedelta(seconds=10),
            time_quality="plausible",
        )
        return CoverObservation.objects.create(
            submission=submission,
            independence_group_key=key,
            reported_price_cents=price,
            interaction_kind="direct",
            admission_snapshot={"resolverVersion": "cover_trust_v1", **kwargs.pop("snapshot", {})},
            **kwargs,
        )

    observation(0, 1000, actor_key)
    latest = observation(5, 1500, actor_key, snapshot={"rapidSpam": True})
    singleton_echo = observation(
        10,
        2000,
        uuid.uuid4(),
        displayed_source="historical",
        displayed_price_cents=2000,
        price_prefilled=True,
        price_touched=False,
    )
    impossible = observation(15, 2500, uuid.uuid4(), snapshot={"impossibleMovement": True})
    cutoff = timezone.now()

    seen, rows, receipts = completed_training_selection(cutoff)
    release = train_completed_night_challenger(knowledge_cutoff=cutoff)

    assert seen == 4
    assert [row.observation_id for row in rows] == [str(latest.submission_id)]
    assert rows[0].weight == pytest.approx(0.6)
    assert str(singleton_echo.submission_id) not in {row.observation_id for row in rows}
    assert str(impossible.submission_id) not in {row.observation_id for row in rows}
    assert release.evaluation_metrics["observations"] == len(receipts) == 1
    assert release.evaluation_metrics["baselineReleaseId"] == str(baseline.id)
    assert release.parameters_or_artifact["observations"] == [
        {
            "observation_id": row.observation_id,
            "venue_id": row.venue_id,
            "observed_at": row.observed_at.isoformat(),
            "available_at": row.available_at.isoformat(),
            "service_date": row.service_date.isoformat(),
            "price_cents": row.price_cents,
            "weight": row.weight,
        }
        for row in rows
    ]
