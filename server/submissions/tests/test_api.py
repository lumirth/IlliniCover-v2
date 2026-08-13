import uuid
from datetime import timedelta

import pytest
from covers.models import CoverDecision, CoverObservation
from django.test import Client
from django.test.utils import override_settings
from django.utils import timezone
from venues.models import Venue

from submissions.models import Submission, SubmissionPrivateContext


def installation_headers(client: Client) -> dict[str, str]:
    raw_token = "ic_install_" + uuid.uuid4().hex + uuid.uuid4().hex
    issued = client.post(
        "/api/v2/installations",
        data={"requestId": str(uuid.uuid4()), "installationToken": raw_token},
        content_type="application/json",
    ).json()
    return {"X-Installation-Token": issued["token"]}


def cover_payload(venue: Venue, submission_id: uuid.UUID, price: int = 2000) -> dict:
    return {
        "submissionId": str(submission_id),
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "vantagePoint": "outside",
        "location": {
            "latitude": 40.11044,
            "longitude": -88.23825,
            "accuracyMeters": 12,
        },
        "cover": {
            "priceCents": price,
            "interaction": "manual",
            "pricePrefilled": False,
            "priceTouched": True,
        },
        "vibes": [{"dimension": "line_length", "value": "long"}],
        "clientPlatform": "ios",
        "clientVersion": "2.0.0",
        "entryPoint": "card_wrong",
    }


@pytest.mark.django_db
def test_one_ordinary_report_is_atomic_and_becomes_the_live_board_answer():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    payload = cover_payload(venue, uuid.uuid4())

    accepted = client.post(
        "/api/v2/cover-submissions",
        data=payload,
        content_type="application/json",
        headers=installation_headers(client),
    )
    board = client.get("/api/v2/cover")

    assert accepted.status_code == 201
    assert accepted.headers["Cache-Control"] == "no-store"
    assert accepted.json()["duplicate"] is False
    assert accepted.json()["cover"]["price"]["amountCents"] == 2000
    assert accepted.json()["cover"]["source"] == "live"
    assert board.status_code == 200
    assert board.json()["venues"][0]["cover"]["price"]["amountCents"] == 2000
    assert board.json()["venues"][0]["recentReportCount"] == 1
    assert board.json()["venues"][0]["vibes"]["lineLength"] == "long"
    assert CoverObservation.objects.count() == 1


@pytest.mark.django_db
def test_duplicate_retry_returns_original_receipt_and_changed_payload_conflicts():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    headers = installation_headers(client)
    submission_id = uuid.uuid4()
    payload = cover_payload(venue, submission_id)

    original = client.post(
        "/api/v2/cover-submissions", data=payload, content_type="application/json", headers=headers
    )
    duplicate = client.post(
        "/api/v2/cover-submissions", data=payload, content_type="application/json", headers=headers
    )
    changed = client.post(
        "/api/v2/cover-submissions",
        data=cover_payload(venue, submission_id, price=500),
        content_type="application/json",
        headers=headers,
    )

    assert duplicate.status_code == 201
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["cover"]["decisionId"] == original.json()["cover"]["decisionId"]
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_conflict"
    assert Submission.objects.count() == 1
    assert CoverObservation.objects.count() == 1


@pytest.mark.django_db
def test_empty_submission_is_rejected_without_persisting_an_envelope():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    response = client.post(
        "/api/v2/cover-submissions",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
        },
        content_type="application/json",
        headers=installation_headers(client),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_prefilled_or_confirmation_report_requires_a_server_decision_receipt():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    payload = cover_payload(venue, uuid.uuid4())
    payload["cover"].update({"interaction": "correct", "pricePrefilled": True})

    response = client.post(
        "/api/v2/cover-submissions",
        data=payload,
        content_type="application/json",
        headers=installation_headers(client),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_displayed_provenance_is_reconstructed_from_the_server_decision():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    now = timezone.now()
    decision = CoverDecision.objects.create(
        venue=venue,
        target_time=now,
        knowledge_cutoff=now,
        result_price_kind=CoverDecision.PriceKind.SINGLE,
        result_price_cents=1_000,
        source=CoverDecision.Source.HISTORICAL,
        status="historical",
        evidence_revision="served:historical",
        resolver_version="cover_resolver_v1",
    )
    payload = cover_payload(venue, uuid.uuid4(), price=1_500)
    payload["cover"].update(
        {
            "displayedDecisionId": str(decision.id),
            "displayedSource": "live",
            "displayedPriceKind": "range",
            "displayedPriceCents": None,
            "displayedPriceLowCents": 5_000,
            "displayedPriceHighCents": 7_000,
        }
    )
    client = Client()

    response = client.post(
        "/api/v2/cover-submissions",
        data=payload,
        content_type="application/json",
        headers=installation_headers(client),
    )

    assert response.status_code == 201
    observation = CoverObservation.objects.get()
    assert observation.displayed_decision == decision
    assert observation.displayed_source == "historical"
    assert observation.displayed_price_kind == "single"
    assert observation.displayed_price_cents == 1_000
    assert observation.displayed_price_low_cents is None
    assert observation.displayed_price_high_cents is None


@pytest.mark.django_db
@pytest.mark.parametrize("price", [7_001, 10**100])
def test_cover_price_above_product_boundary_is_rejected_before_persistence(price):
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()

    response = client.post(
        "/api/v2/cover-submissions",
        data=cover_payload(venue, uuid.uuid4(), price=price),
        content_type="application/json",
        headers=installation_headers(client),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert Submission.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("price", [1, 499, 501, 1_250, 6_999])
def test_cover_price_outside_five_dollar_steps_is_rejected_before_persistence(price):
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()

    response = client.post(
        "/api/v2/cover-submissions",
        data=cover_payload(venue, uuid.uuid4(), price=price),
        content_type="application/json",
        headers=installation_headers(client),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert Submission.objects.count() == 0
    assert CoverObservation.objects.count() == 0


@pytest.mark.django_db
def test_cover_price_at_product_boundary_is_accepted():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()

    response = client.post(
        "/api/v2/cover-submissions",
        data=cover_payload(venue, uuid.uuid4(), price=7_000),
        content_type="application/json",
        headers=installation_headers(client),
    )

    assert response.status_code == 201
    assert CoverObservation.objects.get().reported_price_cents == 7_000


@pytest.mark.django_db
def test_singleton_untouched_historical_echo_does_not_create_live_decision():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    now = timezone.now()
    displayed = CoverDecision.objects.create(
        venue=venue,
        target_time=now,
        knowledge_cutoff=now,
        result_price_kind=CoverDecision.PriceKind.SINGLE,
        result_price_cents=1_000,
        source=CoverDecision.Source.HISTORICAL,
        status="historical",
        evidence_revision="served:historical-echo",
        resolver_version="cover_resolver_v1",
    )
    payload = cover_payload(venue, uuid.uuid4(), price=1000)
    payload["cover"].update(
        {
            "interaction": "quick_confirm",
            "displayedDecisionId": str(displayed.id),
            "pricePrefilled": True,
            "priceTouched": False,
        }
    )

    response = client.post(
        "/api/v2/cover-submissions",
        data=payload,
        content_type="application/json",
        headers=installation_headers(client),
    )

    assert response.status_code == 201
    assert response.json()["cover"] is None
    assert CoverObservation.objects.count() == 1
    assert CoverDecision.objects.count() == 1


@pytest.mark.django_db
def test_cover_board_honors_if_none_match_without_losing_cache_metadata():
    Venue.objects.create(slug="kams", name="KAMS")
    client = Client()

    first = client.get("/api/v2/cover")
    not_modified = client.get("/api/v2/cover", headers={"If-None-Match": first.headers["ETag"]})

    assert first.status_code == 200
    assert first.headers["ETag"].startswith('"')
    assert not_modified.status_code == 304
    assert not_modified.content == b""
    assert not_modified.headers["ETag"] == first.headers["ETag"]


@pytest.mark.django_db
def test_cover_board_etag_is_stable_within_generation_bucket(monkeypatch):
    Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    base = timezone.now().replace(second=1, microsecond=0)
    calls = {"value": 0}

    def within_bucket_now():
        calls["value"] += 1
        return base if calls["value"] <= 2 else base + timedelta(seconds=8)

    monkeypatch.setattr("covers.services.timezone.now", within_bucket_now)

    first = client.get("/api/v2/cover")
    second = client.get("/api/v2/cover", headers={"If-None-Match": first.headers["ETag"]})

    assert second.status_code == 304


@pytest.mark.django_db
def test_new_evidence_invalidates_bucket_and_freshness_uses_observation_age(monkeypatch):
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    base = timezone.now().replace(second=1, microsecond=0)
    monkeypatch.setattr("covers.services.timezone.now", lambda: base)
    first = client.get("/api/v2/cover")
    payload = cover_payload(venue, uuid.uuid4())
    payload["observedAt"] = (base - timedelta(minutes=10)).isoformat()

    accepted = client.post(
        "/api/v2/cover-submissions",
        data=payload,
        content_type="application/json",
        headers=installation_headers(client),
    )
    refreshed = client.get("/api/v2/cover", headers={"If-None-Match": first.headers["ETag"]})

    assert accepted.status_code == 201
    assert accepted.json()["cover"]["freshnessSeconds"] == 600
    assert refreshed.status_code == 200
    assert refreshed.headers["ETag"] != first.headers["ETag"]
    assert refreshed.json()["venues"][0]["cover"]["freshnessSeconds"] == 600
    submission = Submission.objects.get(pk=payload["submissionId"])
    decision = CoverDecision.objects.get(pk=accepted.json()["cover"]["decisionId"])
    assert decision.target_time == submission.received_at_server
    assert decision.knowledge_cutoff == submission.received_at_server


@pytest.mark.django_db
def test_delayed_offline_report_is_preserved_without_becoming_fresh_live_state():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    payload = cover_payload(venue, uuid.uuid4())
    payload["observedAt"] = (timezone.now() - timedelta(hours=2)).isoformat()

    accepted = client.post(
        "/api/v2/cover-submissions",
        data=payload,
        content_type="application/json",
        headers=installation_headers(client),
    )
    board = client.get("/api/v2/cover")

    assert accepted.status_code == 201
    assert accepted.json()["cover"] is None
    assert CoverObservation.objects.count() == 1
    assert board.json()["venues"][0]["cover"]["source"] == "unavailable"
    assert board.json()["venues"][0]["vibes"]["lineLength"] is None


@pytest.mark.django_db
@override_settings(
    SUBMISSION_RATE_LIMITS={
        "actor": (1, 600),
        "account": (30, 600),
        "venue": (120, 600),
        "network": (60, 600),
    }
)
def test_layered_actor_limit_rejects_second_distinct_submission_but_not_idempotent_retry():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    headers = installation_headers(client)
    first_payload = cover_payload(venue, uuid.uuid4())
    second_payload = cover_payload(venue, uuid.uuid4())

    first = client.post(
        "/api/v2/cover-submissions",
        data=first_payload,
        content_type="application/json",
        headers=headers,
    )
    duplicate = client.post(
        "/api/v2/cover-submissions",
        data=first_payload,
        content_type="application/json",
        headers=headers,
    )
    limited = client.post(
        "/api/v2/cover-submissions",
        data=second_payload,
        content_type="application/json",
        headers=headers,
    )

    assert first.status_code == 201
    assert duplicate.status_code == 201
    assert limited.status_code == 429


@pytest.mark.django_db
def test_location_distance_is_a_frozen_trust_input_and_impossible_movement_is_excluded():
    first_venue = Venue.objects.create(
        slug="kams", name="KAMS", latitude=40.11044, longitude=-88.23825
    )
    second_venue = Venue.objects.create(
        slug="remote", name="Remote", latitude=41.8781, longitude=-87.6298
    )
    client = Client()
    headers = installation_headers(client)
    first_payload = cover_payload(first_venue, uuid.uuid4())
    first_time = timezone.now() - timedelta(minutes=1)
    first_payload["observedAt"] = first_time.isoformat()
    first = client.post(
        "/api/v2/cover-submissions",
        data=first_payload,
        content_type="application/json",
        headers=headers,
    )
    second_payload = cover_payload(second_venue, uuid.uuid4())
    second_payload["location"].update({"latitude": 41.8781, "longitude": -87.6298})
    second_payload["observedAt"] = timezone.now().isoformat()
    second = client.post(
        "/api/v2/cover-submissions",
        data=second_payload,
        content_type="application/json",
        headers=headers,
    )

    first_observation = CoverObservation.objects.get(submission_id=first_payload["submissionId"])
    second_observation = CoverObservation.objects.get(submission_id=second_payload["submissionId"])
    assert first.status_code == 201
    assert first_observation.admission_snapshot["distanceToVenueM"] < 1
    assert second.status_code == 201
    assert second.json()["cover"] is None
    assert second_observation.admission_snapshot["impossibleMovement"] is True
    detail = client.get(f"/api/v2/venues/{second_venue.slug}/cover")
    history = client.get(f"/api/v2/venues/{second_venue.slug}/cover/history")
    board = client.get("/api/v2/cover")
    remote_card = next(card for card in board.json()["venues"] if card["venue"]["slug"] == "remote")
    assert detail.json()["recentReports"] == []
    assert detail.json()["vibes"]["lineLength"] is None
    assert history.json()["reports"] == []
    assert remote_card["recentReportCount"] == 0


@pytest.mark.django_db
def test_vibe_only_impossible_movement_is_retained_but_not_public():
    first_venue = Venue.objects.create(
        slug="first-vibe", name="First", latitude=40.11044, longitude=-88.23825
    )
    second_venue = Venue.objects.create(
        slug="remote-vibe", name="Remote", latitude=41.8781, longitude=-87.6298
    )
    client = Client()
    headers = installation_headers(client)
    first_time = timezone.now() - timedelta(minutes=1)

    def submit(venue, observed_at, latitude, longitude):
        return client.post(
            "/api/v2/cover-submissions",
            data={
                "submissionId": str(uuid.uuid4()),
                "venueId": str(venue.id),
                "observedAt": observed_at.isoformat(),
                "location": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "accuracyMeters": 10,
                },
                "vibes": [{"dimension": "line_length", "value": "long"}],
            },
            content_type="application/json",
            headers=headers,
        )

    assert submit(first_venue, first_time, 40.11044, -88.23825).status_code == 201
    assert submit(second_venue, timezone.now(), 41.8781, -87.6298).status_code == 201

    remote_context = SubmissionPrivateContext.objects.filter(submission__venue=second_venue).get()
    remote_card = next(
        card
        for card in client.get("/api/v2/cover").json()["venues"]
        if card["venue"]["slug"] == second_venue.slug
    )
    assert remote_context.evidence_snapshot["impossibleMovement"] is True
    assert remote_card["vibes"]["lineLength"] is None
    assert client.get(f"/api/v2/venues/{second_venue.slug}/cover").json()["recentReports"] == []


@pytest.mark.django_db
def test_vibe_only_rapid_repeat_cannot_replace_the_public_value():
    venue = Venue.objects.create(slug="vibe", name="Vibe")
    client = Client()
    headers = installation_headers(client)
    start = timezone.now() - timedelta(seconds=2)

    for offset, value in ((0, "short"), (1, "long")):
        response = client.post(
            "/api/v2/cover-submissions",
            data={
                "submissionId": str(uuid.uuid4()),
                "venueId": str(venue.id),
                "observedAt": (start + timedelta(seconds=offset)).isoformat(),
                "vibes": [{"dimension": "line_length", "value": value}],
            },
            content_type="application/json",
            headers=headers,
        )
        assert response.status_code == 201

    contexts = SubmissionPrivateContext.objects.filter(submission__venue=venue).order_by(
        "submission__observed_at_client"
    )
    card = client.get("/api/v2/cover").json()["venues"][0]
    reports = client.get(f"/api/v2/venues/{venue.slug}/cover").json()["recentReports"]
    assert contexts[1].evidence_snapshot["rapidSpam"] is True
    assert card["vibes"]["lineLength"] == "short"
    assert len(reports) == 1
    assert reports[0]["priceCents"] is None
    assert reports[0]["interaction"] == "vibes"
    assert reports[0]["vibes"] == ["line_length:short"]
