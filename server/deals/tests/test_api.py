import hashlib
import hmac
import json
import uuid
from datetime import datetime, time, timedelta

import pytest
from covers.services import service_date_for
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client
from django.utils import timezone
from identity.models import Account, ActorAccountLink, InstallationActor
from identity.tokens import issue_session_token
from operations.models import DatasetRelease
from submissions.models import Submission
from venues.models import Venue

from deals.models import (
    DealAlias,
    DealDefinition,
    DealEvidenceEvent,
    DealFamily,
    DealPrediction,
    DealPredictionRelease,
    HistoricalDealFact,
)
from deals.schemas import DealEvidenceInputSchema


def issue_token(client: Client) -> str:
    raw_token = "ic_install_" + uuid.uuid4().hex + uuid.uuid4().hex
    response = client.post(
        "/api/v2/installations",
        data={"requestId": str(uuid.uuid4()), "installationToken": raw_token},
        content_type="application/json",
    )
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()["token"]


@pytest.mark.django_db
def test_deal_evidence_response_with_installation_credential_is_not_cacheable():
    venue = Venue.objects.create(slug="private-deal", name="Private Deal")
    client = Client()
    observed_at = timezone.now()

    response = client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": observed_at.isoformat(),
            "action": "ADD_MISSING",
            "serviceDateLocal": service_date_for(observed_at).isoformat(),
            "submittedDealShape": {
                "displayName": "$3 wells",
                "category": "drink",
                "priceKind": "single",
                "priceCents": 300,
            },
        },
        content_type="application/json",
        headers={"X-Installation-Token": issue_token(client)},
    )

    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_deal_slate_keeps_empty_venues_and_unknown_timing_unknown():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    Venue.objects.create(slug="joes", name="Joe's")
    DealDefinition.objects.create(
        venue=venue,
        display_name="$5 wells",
        category="drink",
        price_kind="absolute",
        price_cents=500,
        timing_description="",
        timing_known=False,
    )

    response = Client().get("/api/v2/deals")

    assert response.status_code == 200
    rows = {row["venue"]["slug"]: row["deals"] for row in response.json()["venues"]}
    assert rows["joes"] == []
    assert rows["kams"][0]["timingKnown"] is False
    assert rows["kams"][0]["timingDescription"] is None


@pytest.mark.django_db
def test_add_missing_deal_evidence_preserves_shape_and_is_idempotent():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    token = issue_token(client)
    submission_id = uuid.uuid4()
    payload = {
        "submissionId": str(submission_id),
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "action": "ADD_MISSING",
        "serviceDateLocal": timezone.localdate().isoformat(),
        "submittedDealShape": {
            "displayName": "$5 wells",
            "category": "drink",
            "priceKind": "absolute",
            "priceCents": 500,
            "timingKnown": False,
        },
    }

    first = client.post(
        "/api/v2/deal-evidence",
        data=payload,
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )
    retry = client.post(
        "/api/v2/deal-evidence",
        data=payload,
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )

    normalized = DealEvidenceInputSchema.model_validate(payload)
    canonical = json.dumps(
        normalized.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    stored_fingerprint = Submission.objects.get(pk=submission_id).request_fingerprint
    raw_fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    expected_fingerprint = hmac.new(
        settings.SECRET_KEY.encode(),
        f"accepted-deal-evidence-payload-v1:{canonical}".encode(),
        hashlib.sha256,
    ).hexdigest()

    assert stored_fingerprint != raw_fingerprint
    assert stored_fingerprint == expected_fingerprint

    assert first.status_code == 201
    assert retry.status_code == 201
    assert retry.json()["duplicate"] is True
    assert retry.json()["eventId"] == first.json()["eventId"]
    event = DealEvidenceEvent.objects.get()
    assert event.submitted_deal_shape["displayName"] == "wells"
    assert event.submitted_deal_shape["timingKnown"] is False
    assert "timingDescription" in event.submitted_deal_shape


@pytest.mark.django_db
def test_slate_uses_materialized_authoritative_predictions_with_prediction_identity():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    deal = DealDefinition.objects.create(
        venue=venue,
        display_name="$5 wells",
        category="drink",
        price_kind="single",
        price_cents=500,
    )
    release = DealPredictionRelease.objects.create(
        predictor_version="test",
        training_data_revision="facts-v1",
        code_revision="test",
        is_authoritative=True,
    )
    prediction = DealPrediction.objects.create(
        release=release,
        venue=venue,
        deal_definition=deal,
        service_date_local=timezone.localdate(),
        support_nights=2,
        comparable_nights=3,
        latest_evidence_date=timezone.localdate(),
        rank=1,
    )

    row = Client().get("/api/v2/deals").json()["venues"][0]["deals"][0]

    assert row["predictionId"] == str(prediction.id)
    assert row["status"] == "likely"
    assert row["latestActivityAt"] is None


@pytest.mark.django_db
def test_slate_latest_activity_tracks_admitted_evidence_before_public_state_changes():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    deal = DealDefinition.objects.create(
        venue=venue,
        display_name="$5 wells",
        category="drink",
        price_kind="single",
        price_cents=500,
    )
    client = Client()
    token = issue_token(client)
    observed_at = timezone.now() - timedelta(minutes=10)

    response = client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": observed_at.isoformat(),
            "action": "CONFIRM_PRESENT",
            "targetDealId": str(deal.id),
            "serviceDateLocal": service_date_for(observed_at).isoformat(),
        },
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )

    assert response.status_code == 201
    event = DealEvidenceEvent.objects.select_related("submission").get()
    row = client.get("/api/v2/deals").json()["venues"][0]["deals"][0]
    public_activity = datetime.fromisoformat(row["latestActivityAt"])
    assert row["status"] == "likely"
    assert abs(public_activity - event.submission.observed_at_client) < timedelta(milliseconds=1)
    assert public_activity != event.submission.received_at_server
    assert public_activity != deal.created_at

    correction = client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CORRECT",
            "targetDealId": str(deal.id),
            "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
            "submittedDealShape": {
                "displayName": "$6 wells",
                "category": "drink",
                "priceKind": "single",
                "priceCents": 600,
            },
        },
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )

    assert correction.status_code == 201
    correction_event = DealEvidenceEvent.objects.select_related("submission").get(
        pk=correction.json()["eventId"]
    )
    unchanged = client.get("/api/v2/deals").json()["venues"][0]["deals"][0]
    assert unchanged["displayName"] == "wells"
    assert abs(
        datetime.fromisoformat(unchanged["latestActivityAt"])
        - correction_event.submission.observed_at_client
    ) < timedelta(milliseconds=1)


@pytest.mark.django_db
def test_deal_order_without_same_night_evidence_uses_persisted_prediction_rank():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    service_date = service_date_for(timezone.now())
    release = DealPredictionRelease.objects.create(
        predictor_version="rank-test",
        training_data_revision="rank-test",
        code_revision="test",
        is_authoritative=True,
    )
    first = DealDefinition.objects.create(
        venue=venue,
        display_name="Zulu first by predictor",
        category="drink",
        price_kind="single",
        price_cents=500,
    )
    first_prediction = DealPrediction.objects.create(
        release=release,
        venue=venue,
        deal_definition=first,
        service_date_local=service_date,
        support_nights=3,
        comparable_nights=3,
        latest_evidence_date=service_date - timedelta(days=7),
        rank=1,
    )
    second = DealDefinition.objects.create(
        venue=venue,
        display_name="Alpha second by predictor",
        category="drink",
        price_kind="single",
        price_cents=600,
    )
    second_prediction = DealPrediction.objects.create(
        release=release,
        venue=venue,
        deal_definition=second,
        service_date_local=service_date,
        support_nights=2,
        comparable_nights=3,
        latest_evidence_date=service_date - timedelta(days=7),
        rank=2,
    )

    rows = Client().get("/api/v2/deals").json()["venues"][0]["deals"]

    assert first_prediction.created_at < second_prediction.created_at
    assert [row["displayName"] for row in rows] == [
        "Zulu first by predictor",
        "Alpha second by predictor",
    ]
    assert all("rank" not in row for row in rows)


@pytest.mark.django_db
def test_deal_order_uses_casefolded_name_then_stable_id_without_evidence_or_rank():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    first_same_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second_same_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    definitions = [
        DealDefinition.objects.create(
            id=second_same_id,
            venue=venue,
            display_name="Same",
            category="drink",
            price_kind="single",
            price_cents=600,
        ),
        DealDefinition.objects.create(
            venue=venue,
            display_name="zulu",
            category="drink",
            price_kind="single",
            price_cents=700,
        ),
        DealDefinition.objects.create(
            id=first_same_id,
            venue=venue,
            display_name="Same",
            category="drink",
            price_kind="single",
            price_cents=500,
        ),
        DealDefinition.objects.create(
            venue=venue,
            display_name="alpha",
            category="drink",
            price_kind="single",
            price_cents=400,
        ),
    ]

    rows = Client().get("/api/v2/deals").json()["venues"][0]["deals"]

    expected_ids = [
        str(definitions[3].id),
        str(first_same_id),
        str(second_same_id),
        str(definitions[1].id),
    ]
    assert [row["id"] for row in rows] == expected_ids


@pytest.mark.django_db
def test_same_night_evidence_orders_a_lower_ranked_prediction_first():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    service_date = service_date_for(timezone.now())
    release = DealPredictionRelease.objects.create(
        predictor_version="evidence-order-test",
        training_data_revision="evidence-order-test",
        code_revision="test",
        is_authoritative=True,
    )
    predictions = []
    for rank, name in ((1, "Alpha rank one"), (2, "Zulu rank two")):
        definition = DealDefinition.objects.create(
            venue=venue,
            display_name=name,
            category="drink",
            price_kind="single",
            price_cents=rank * 100,
        )
        predictions.append(
            DealPrediction.objects.create(
                release=release,
                venue=venue,
                deal_definition=definition,
                service_date_local=service_date,
                support_nights=2,
                comparable_nights=3,
                latest_evidence_date=service_date - timedelta(days=7),
                rank=rank,
            )
        )
    client = Client()
    token = issue_token(client)
    response = client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CONFIRM_PRESENT",
            "targetPredictionId": str(predictions[1].id),
            "serviceDateLocal": service_date.isoformat(),
        },
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )

    rows = client.get("/api/v2/deals").json()["venues"][0]["deals"]

    assert response.status_code == 201
    assert [row["displayName"] for row in rows] == ["Zulu rank two", "Alpha rank one"]

    first_client = Client()
    first_token = issue_token(first_client)
    first_response = first_client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CONFIRM_PRESENT",
            "targetPredictionId": str(predictions[0].id),
            "serviceDateLocal": service_date.isoformat(),
        },
        content_type="application/json",
        headers={"X-Installation-Token": first_token},
    )
    evidence_events = {
        event.id: event.submission_id
        for event in DealEvidenceEvent.objects.filter(
            id__in=[response.json()["eventId"], first_response.json()["eventId"]]
        )
    }
    older = timezone.now()
    Submission.objects.filter(
        id=evidence_events[uuid.UUID(first_response.json()["eventId"])]
    ).update(observed_at_client=older)
    Submission.objects.filter(id=evidence_events[uuid.UUID(response.json()["eventId"])]).update(
        observed_at_client=older + timedelta(seconds=1)
    )

    newest_first = Client().get("/api/v2/deals").json()["venues"][0]["deals"]
    assert first_response.status_code == 201
    assert [row["displayName"] for row in newest_first] == [
        "Zulu rank two",
        "Alpha rank one",
    ]


@pytest.mark.django_db
def test_admitted_correction_replaces_target_and_inherits_its_prediction_rank():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    service_date = service_date_for(timezone.now())
    release = DealPredictionRelease.objects.create(
        predictor_version="correction-rank-test",
        training_data_revision="correction-rank-test",
        code_revision="test",
        is_authoritative=True,
    )
    predictions = []
    for rank, name in ((1, "Original target"), (2, "Alpha second prediction")):
        definition = DealDefinition.objects.create(
            venue=venue,
            display_name=name,
            category="drink",
            price_kind="single",
            price_cents=rank * 100,
        )
        predictions.append(
            DealPrediction.objects.create(
                release=release,
                venue=venue,
                deal_definition=definition,
                service_date_local=service_date,
                support_nights=2,
                comparable_nights=3,
                latest_evidence_date=service_date - timedelta(days=7),
                rank=rank,
            )
        )

    correction_client = Client()
    correction_token = issue_token(correction_client)
    correction = correction_client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CORRECT",
            "targetPredictionId": str(predictions[0].id),
            "serviceDateLocal": service_date.isoformat(),
            "submittedDealShape": {
                "displayName": "Zulu corrected target",
                "category": "drink",
                "priceKind": "single",
                "priceCents": 900,
            },
        },
        content_type="application/json",
        headers={"X-Installation-Token": correction_token},
        REMOTE_ADDR="203.0.113.11",
    )
    correction_id = correction.json()["eventId"]

    pending = correction_client.get("/api/v2/deals").json()["venues"][0]["deals"]
    assert correction.status_code == 201
    assert pending[0]["id"] == str(predictions[0].deal_definition_id)
    assert all(row["displayName"] != "Zulu corrected target" for row in pending)

    confirmation_client = Client()
    confirmation_token = issue_token(confirmation_client)
    confirmation = confirmation_client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CONFIRM_PRESENT",
            "targetDealId": correction_id,
            "serviceDateLocal": service_date.isoformat(),
        },
        content_type="application/json",
        headers={"X-Installation-Token": confirmation_token},
        REMOTE_ADDR="203.0.113.12",
    )
    second_client = Client()
    second_token = issue_token(second_client)
    second_confirmation = second_client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CONFIRM_PRESENT",
            "targetPredictionId": str(predictions[1].id),
            "serviceDateLocal": service_date.isoformat(),
        },
        content_type="application/json",
        headers={"X-Installation-Token": second_token},
        REMOTE_ADDR="203.0.113.13",
    )
    assert confirmation.status_code == 201
    assert second_confirmation.status_code == 201

    tied_activity_at = timezone.now() + timedelta(seconds=1)
    event_ids = [confirmation.json()["eventId"], second_confirmation.json()["eventId"]]
    submission_ids = DealEvidenceEvent.objects.filter(id__in=event_ids).values_list(
        "submission_id", flat=True
    )
    Submission.objects.filter(id__in=submission_ids).update(observed_at_client=tied_activity_at)

    corrected = Client().get("/api/v2/deals").json()["venues"][0]["deals"]
    assert corrected[0]["id"] == correction_id
    assert [row["displayName"] for row in corrected] == [
        "Original target",
        "Alpha second prediction",
    ]
    assert corrected[0]["priceCents"] == 900


@pytest.mark.django_db
def test_deal_suggestions_search_canonical_registry_and_keep_full_shape():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    HistoricalDealFact.objects.create(
        source_record_key="fact-1",
        source_dataset="test",
        venue=venue,
        family=family,
        private_search_text="lit pitcher",
        display_name="$5 Wells",
        category="drink",
        price_kind="single",
        price_cents=500,
        unit="draft vessel",
        service_date_local=timezone.localdate(),
        timing_kind="unknown",
        source_post_key="post-1",
        source_payload_hash="a" * 64,
    )

    response = Client().get("/api/v2/deal-suggestions", {"q": "well", "limit": 6})

    assert response.status_code == 200
    suggestion = response.json()["suggestions"][0]
    assert suggestion["canonicalFamilyId"] == str(family.id)
    assert suggestion["displayName"] == "Wells"
    assert suggestion["priceCents"] == 500
    assert suggestion["sourceScope"] == "global"
    assert suggestion["lastSeenServiceDateLocal"] == timezone.localdate().isoformat()
    assert suggestion["matchedSource"] == "canonical"
    assert suggestion["matchedText"] == "Wells"

    display_search = Client().get("/api/v2/deal-suggestions", {"q": "$5", "limit": 6})
    display_suggestion = display_search.json()["suggestions"][0]
    assert display_suggestion["canonicalFamilyId"] == str(family.id)
    assert display_suggestion["matchedSource"] == "display_name"
    assert display_suggestion["matchedText"] == "Wells"

    DealAlias.objects.create(family=family, alias="Happy Hour Rail Drinks")
    alias_search = Client().get("/api/v2/deal-suggestions", {"q": "happy", "limit": 6})
    alias_suggestion = alias_search.json()["suggestions"][0]
    assert alias_suggestion["canonicalFamilyId"] == str(family.id)
    assert alias_suggestion["matchedSource"] == "alias"
    assert alias_suggestion["matchedText"] == "Happy Hour Rail Drinks"

    recent = Client().get("/api/v2/deal-suggestions", {"limit": 6}).json()["suggestions"][0]
    assert recent["matchedSource"] is None
    assert recent["matchedText"] is None

    raw_alias_search = (
        Client()
        .get("/api/v2/deal-suggestions", {"q": "lit pitcher", "limit": 6})
        .json()["suggestions"][0]
    )
    assert raw_alias_search["matchedSource"] == "historical_alias"
    assert raw_alias_search["matchedText"] is None

    unit_search = (
        Client()
        .get("/api/v2/deal-suggestions", {"q": "vessel", "limit": 6})
        .json()["suggestions"][0]
    )
    assert unit_search["matchedSource"] == "unit"
    assert unit_search["matchedText"] == "draft vessel"

    punctuation_only = Client().get("/api/v2/deal-suggestions", {"q": "###", "limit": 6})
    assert punctuation_only.status_code == 200
    assert punctuation_only.json()["suggestions"] == []


@pytest.mark.django_db
def test_deal_suggestions_preserve_same_family_variants_and_match_the_queried_shape():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    DealAlias.objects.create(family=family, alias="Rail Drinks")
    today = timezone.localdate()
    rows = (
        ("three-old", "$3 Wells", 300, "cup", today - timedelta(days=7)),
        ("three-new", "$3 Wells", 300, "cup", today - timedelta(days=1)),
        ("five", "$5 Wells", 500, "pitcher", today),
    )
    for key, name, price, unit, service_date in rows:
        HistoricalDealFact.objects.create(
            source_record_key=key,
            source_dataset="test",
            venue=venue,
            family=family,
            display_name=name,
            category="drink",
            price_kind="single",
            price_cents=price,
            unit=unit,
            service_date_local=service_date,
            timing_kind="unknown",
            source_post_key=key,
            source_payload_hash="a" * 64,
        )

    canonical = (
        Client().get("/api/v2/deal-suggestions", {"q": "well", "limit": 6}).json()["suggestions"]
    )
    assert [(row["displayName"], row["priceCents"], row["unit"]) for row in canonical] == [
        ("Wells", 500, "pitcher"),
        ("Wells", 300, "cup"),
    ]
    assert all(row["matchedSource"] == "canonical" for row in canonical)

    older_display_match = (
        Client().get("/api/v2/deal-suggestions", {"q": "$3", "limit": 6}).json()["suggestions"]
    )
    assert len(older_display_match) == 1
    assert older_display_match[0]["displayName"] == "Wells"
    assert (
        older_display_match[0]["lastSeenServiceDateLocal"]
        == (today - timedelta(days=1)).isoformat()
    )
    assert older_display_match[0]["matchedSource"] == "display_name"
    assert older_display_match[0]["matchedText"] == "Wells"

    alias = (
        Client().get("/api/v2/deal-suggestions", {"q": "rail", "limit": 6}).json()["suggestions"]
    )
    assert len(alias) == 2
    assert all(row["matchedSource"] == "alias" for row in alias)
    assert all(row["matchedText"] == "Rail Drinks" for row in alias)


@pytest.mark.django_db
def test_deal_suggestion_with_venue_ranks_local_shape_before_global_shapes():
    kams = Venue.objects.create(slug="kams", name="KAMS")
    joes = Venue.objects.create(slug="joes", name="Joe's")
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    for key, venue, price in (("kams", kams, 500), ("joes", joes, 300)):
        HistoricalDealFact.objects.create(
            source_record_key=key,
            source_dataset="test",
            venue=venue,
            family=family,
            display_name=f"${price // 100} Wells",
            category="drink",
            price_kind="single",
            price_cents=price,
            service_date_local=timezone.localdate(),
            timing_kind="unknown",
            source_post_key=key,
            source_payload_hash="a" * 64,
        )

    suggestions = (
        Client()
        .get("/api/v2/deal-suggestions", {"q": "wells", "venue": "kams"})
        .json()["suggestions"]
    )

    assert [(row["priceCents"], row["sourceScope"]) for row in suggestions] == [
        (500, "venue"),
        (300, "global"),
    ]
    assert all(
        row["lastSeenServiceDateLocal"] == timezone.localdate().isoformat() for row in suggestions
    )


@pytest.mark.django_db
def test_deal_suggestion_marks_a_shared_variant_local_and_keeps_latest_seen_date():
    kams = Venue.objects.create(slug="kams", name="KAMS")
    joes = Venue.objects.create(slug="joes", name="Joe's")
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    today = timezone.localdate()
    for key, venue, service_date in (
        ("kams", kams, today - timedelta(days=2)),
        ("joes", joes, today),
    ):
        HistoricalDealFact.objects.create(
            source_record_key=key,
            source_dataset="test",
            venue=venue,
            family=family,
            display_name="$5 Wells",
            category="drink",
            price_kind="single",
            price_cents=500,
            unit="drink",
            service_date_local=service_date,
            timing_kind="unknown",
            source_post_key=key,
            source_payload_hash="a" * 64,
        )

    suggestions = (
        Client()
        .get("/api/v2/deal-suggestions", {"q": "wells", "venue": "kams"})
        .json()["suggestions"]
    )

    assert len(suggestions) == 1
    assert suggestions[0]["sourceScope"] == "venue"
    assert suggestions[0]["lastSeenServiceDateLocal"] == today.isoformat()


@pytest.mark.django_db
def test_deal_evidence_rejects_prediction_from_another_venue():
    kams = Venue.objects.create(slug="kams", name="KAMS")
    joes = Venue.objects.create(slug="joes", name="Joe's")
    definition = DealDefinition.objects.create(
        venue=kams, display_name="Wells", category="drink", price_kind="single", price_cents=500
    )
    release = DealPredictionRelease.objects.create(
        predictor_version="target-test",
        training_data_revision="target-test",
        code_revision="test",
        is_authoritative=True,
    )
    prediction = DealPrediction.objects.create(
        release=release,
        venue=kams,
        deal_definition=definition,
        service_date_local=timezone.localdate(),
        support_nights=2,
        comparable_nights=3,
        latest_evidence_date=timezone.localdate(),
        rank=1,
    )
    client = Client()
    token = issue_token(client)

    response = client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(joes.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CONFIRM_PRESENT",
            "targetPredictionId": str(prediction.id),
            "serviceDateLocal": timezone.localdate().isoformat(),
        },
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_deal_target"


@pytest.mark.django_db
def test_canonical_deal_requires_independent_add_then_confirm_and_two_denials():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    first_client = Client()
    first_token = issue_token(first_client)
    add = first_client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "ADD_MISSING",
            "serviceDateLocal": timezone.localdate().isoformat(),
            "submittedDealShape": {
                "canonicalFamilyId": str(family.id),
                "displayName": "$5 wells",
                "category": "drink",
                "priceKind": "single",
                "priceCents": 500,
            },
        },
        content_type="application/json",
        headers={"X-Installation-Token": first_token},
        REMOTE_ADDR="203.0.113.1",
    )
    event_id = add.json()["eventId"]

    assert add.status_code == 201
    assert first_client.get("/api/v2/deals").json()["venues"][0]["deals"] == []

    second_client = Client()
    second_token = issue_token(second_client)
    confirm = second_client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CONFIRM_PRESENT",
            "targetDealId": event_id,
            "serviceDateLocal": timezone.localdate().isoformat(),
        },
        content_type="application/json",
        headers={"X-Installation-Token": second_token},
        REMOTE_ADDR="203.0.113.2",
    )
    slate = second_client.get("/api/v2/deals").json()["venues"][0]["deals"]

    assert confirm.status_code == 201
    confirmed_event = DealEvidenceEvent.objects.get(pk=confirm.json()["eventId"])
    assert confirmed_event.target_evidence_id == uuid.UUID(event_id)
    assert slate[0]["id"] == event_id
    assert slate[0]["displayName"] == "Wells"
    assert slate[0]["status"] == "current"

    correction_client = Client()
    correction_token = issue_token(correction_client)
    correction = correction_client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CORRECT",
            "targetDealId": event_id,
            "supersedesEventId": event_id,
            "serviceDateLocal": timezone.localdate().isoformat(),
            "submittedDealShape": {
                "canonicalFamilyId": str(family.id),
                "displayName": "$6 wells",
                "category": "drink",
                "priceKind": "single",
                "priceCents": 600,
            },
        },
        content_type="application/json",
        headers={"X-Installation-Token": correction_token},
        REMOTE_ADDR="203.0.113.3",
    )
    correction_id = correction.json()["eventId"]
    assert correction.status_code == 201
    correction_event = DealEvidenceEvent.objects.get(pk=correction_id)
    assert correction_event.supersedes_id is None
    still_original = correction_client.get("/api/v2/deals").json()["venues"][0]["deals"]
    assert still_original[0]["id"] == event_id

    correction_confirm_client = Client()
    correction_confirm_token = issue_token(correction_confirm_client)
    correction_confirm = correction_confirm_client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CONFIRM_PRESENT",
            "targetDealId": correction_id,
            "serviceDateLocal": timezone.localdate().isoformat(),
        },
        content_type="application/json",
        headers={"X-Installation-Token": correction_confirm_token},
        REMOTE_ADDR="203.0.113.4",
    )
    corrected = correction_confirm_client.get("/api/v2/deals").json()["venues"][0]["deals"]
    assert correction_confirm.status_code == 201
    assert corrected[0]["id"] == correction_id
    assert corrected[0]["displayName"] == "Wells"
    assert corrected[0]["priceCents"] == 600

    for index in (5, 6):
        client = Client()
        token = issue_token(client)
        denied = client.post(
            "/api/v2/deal-evidence",
            data={
                "submissionId": str(uuid.uuid4()),
                "venueId": str(venue.id),
                "observedAt": timezone.now().isoformat(),
                "action": "DENY_PRESENT",
                "targetDealId": correction_id,
                "serviceDateLocal": timezone.localdate().isoformat(),
            },
            content_type="application/json",
            headers={"X-Installation-Token": token},
            REMOTE_ADDR=f"203.0.113.{index}",
        )
        assert denied.status_code == 201
        deals = client.get("/api/v2/deals").json()["venues"][0]["deals"]
        if index == 5:
            assert deals[0]["id"] == correction_id
        else:
            assert all(deal["id"] != correction_id for deal in deals)
            assert deals[0]["id"] == event_id


@pytest.mark.django_db
def test_deal_correction_lineage_cannot_cross_venues():
    first_venue = Venue.objects.create(slug="kams", name="KAMS")
    second_venue = Venue.objects.create(slug="joes", name="Joe's")
    client = Client()
    token = issue_token(client)
    deal = DealDefinition.objects.create(
        venue=first_venue,
        display_name="$5 wells",
        category="drink",
        price_kind="single",
        price_cents=500,
    )
    release = DealPredictionRelease.objects.create(
        predictor_version="lineage-test",
        training_data_revision="lineage-test",
        code_revision="test",
        is_authoritative=True,
    )
    prediction = DealPrediction.objects.create(
        release=release,
        venue=first_venue,
        deal_definition=deal,
        service_date_local=timezone.localdate(),
        support_nights=2,
        comparable_nights=3,
        latest_evidence_date=timezone.localdate(),
        rank=1,
    )
    original_payload = {
        "submissionId": str(uuid.uuid4()),
        "venueId": str(first_venue.id),
        "observedAt": timezone.now().isoformat(),
        "action": "CONFIRM_PRESENT",
        "targetPredictionId": str(prediction.id),
        "serviceDateLocal": timezone.localdate().isoformat(),
    }
    original = client.post(
        "/api/v2/deal-evidence",
        data=original_payload,
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )
    correction_payload = {
        **original_payload,
        "submissionId": str(uuid.uuid4()),
        "venueId": str(second_venue.id),
        "action": "CORRECT",
        "supersedesEventId": original.json()["eventId"],
        "submittedDealShape": {
            "displayName": "$5 wells",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 500,
        },
    }
    correction = client.post(
        "/api/v2/deal-evidence",
        data=correction_payload,
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )

    assert correction.status_code == 422
    assert correction.json()["code"] == "invalid_evidence_lineage"


@pytest.mark.django_db
def test_prediction_targeted_confirmation_and_denial_overlay_authoritative_slate():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    service_date = service_date_for(timezone.now())
    deal = DealDefinition.objects.create(
        venue=venue,
        display_name="$5 wells",
        category="drink",
        price_kind="single",
        price_cents=500,
    )
    release = DealPredictionRelease.objects.create(
        predictor_version="overlay-test",
        training_data_revision="overlay-test",
        code_revision="test",
        is_authoritative=True,
    )
    prediction = DealPrediction.objects.create(
        release=release,
        venue=venue,
        deal_definition=deal,
        service_date_local=service_date,
        support_nights=2,
        comparable_nights=3,
        latest_evidence_date=service_date,
        rank=1,
    )
    common = {
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "targetPredictionId": str(prediction.id),
        "serviceDateLocal": service_date.isoformat(),
    }

    for index in (1, 2):
        client = Client()
        token = issue_token(client)
        confirmed = client.post(
            "/api/v2/deal-evidence",
            data={**common, "submissionId": str(uuid.uuid4()), "action": "CONFIRM_PRESENT"},
            content_type="application/json",
            headers={"X-Installation-Token": token},
            REMOTE_ADDR=f"198.51.100.{index}",
        )
        assert confirmed.status_code == 201
    after_confirmation = Client().get("/api/v2/deals").json()["venues"][0]["deals"]
    assert after_confirmation[0]["status"] == "current"

    for index in (3, 4):
        client = Client()
        token = issue_token(client)
        denied = client.post(
            "/api/v2/deal-evidence",
            data={**common, "submissionId": str(uuid.uuid4()), "action": "DENY_PRESENT"},
            content_type="application/json",
            headers={"X-Installation-Token": token},
            REMOTE_ADDR=f"198.51.100.{index}",
        )
        assert denied.status_code == 201
    assert Client().get("/api/v2/deals").json()["venues"][0]["deals"] == []


@pytest.mark.django_db
def test_stale_delayed_deal_evidence_is_preserved_but_not_overlaid():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    token = issue_token(client)

    observed_at = timezone.now() - timedelta(days=2)
    response = client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": observed_at.isoformat(),
            "action": "ADD_MISSING",
            "serviceDateLocal": service_date_for(observed_at).isoformat(),
            "submittedDealShape": {
                "displayName": "$5 stale wells",
                "category": "drink",
                "priceKind": "single",
                "priceCents": 500,
            },
        },
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )

    assert response.status_code == 201
    assert Submission.objects.get().time_quality == "stale_interaction"
    assert client.get("/api/v2/deals").json()["venues"][0]["deals"] == []


@pytest.mark.django_db
def test_deal_evidence_rejects_client_selected_service_night():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    token = issue_token(client)
    observed_at = timezone.now() - timedelta(days=2)

    response = client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": observed_at.isoformat(),
            "action": "ADD_MISSING",
            "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
            "submittedDealShape": {
                "displayName": "$5 stale wells",
                "category": "drink",
                "priceKind": "single",
                "priceCents": 500,
            },
        },
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_service_date"
    assert Submission.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "shape",
    [
        {"displayName": "bad", "category": "merch", "priceKind": "single", "priceCents": 5},
        {
            "displayName": "bad",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 500,
            "discountPercent": 10,
        },
        {
            "displayName": "bad",
            "category": "drink",
            "priceKind": "range",
            "priceLowCents": 700,
            "priceHighCents": 500,
        },
        {
            "displayName": "bad",
            "category": "drink",
            "priceKind": "unknown",
            "priceCents": 500,
        },
        {
            "displayName": "bad",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 500,
            "timingKnown": True,
        },
        {
            "displayName": "bad",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 10_001,
        },
        {
            "displayName": "bad",
            "category": "drink",
            "priceKind": "range",
            "priceLowCents": 500,
            "priceHighCents": 10**100,
        },
        {"displayName": "   ", "category": "drink", "priceKind": "unknown"},
        {"displayName": "$5", "category": "drink", "priceKind": "single", "priceCents": 500},
    ],
)
def test_malformed_deal_shapes_never_enter_evidence(shape):
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    token = issue_token(client)

    response = client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "ADD_MISSING",
            "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
            "submittedDealShape": shape,
        },
        content_type="application/json",
        headers={"X-Installation-Token": token},
    )

    assert response.status_code == 422
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_corroborated_unresolved_custom_deal_text_remains_private():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    common = {
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "action": "ADD_MISSING",
        "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
        "submittedDealShape": {
            "displayName": "Unreviewed user-authored label",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 500,
            "unit": "Unreviewed user-authored unit",
            "servingFormat": "Unreviewed user-authored serving",
            "timingKnown": True,
            "timingDescription": "Unreviewed user-authored timing",
        },
    }

    event_ids = []
    for index in (1, 2):
        client = Client()
        response = client.post(
            "/api/v2/deal-evidence",
            data={**common, "submissionId": str(uuid.uuid4())},
            content_type="application/json",
            headers={"X-Installation-Token": issue_token(client)},
            REMOTE_ADDR=f"203.0.113.{index}",
        )
        assert response.status_code == 201
        event_ids.append(response.json()["eventId"])

    stored_shapes = list(
        DealEvidenceEvent.objects.filter(id__in=event_ids).values_list(
            "submitted_deal_shape", flat=True
        )
    )
    assert len(stored_shapes) == 2
    assert all(shape["displayName"] == "Unreviewed user-authored label" for shape in stored_shapes)
    assert Client().get("/api/v2/deals").json()["venues"][0]["deals"] == []


@pytest.mark.django_db
def test_corroborated_spoofed_family_id_remains_private():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    common = {
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "action": "ADD_MISSING",
        "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
        "submittedDealShape": {
            "canonicalFamilyId": str(uuid.uuid4()),
            "displayName": "Unreviewed user-authored label",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 500,
        },
    }

    for index in (1, 2):
        client = Client()
        response = client.post(
            "/api/v2/deal-evidence",
            data={**common, "submissionId": str(uuid.uuid4())},
            content_type="application/json",
            headers={"X-Installation-Token": issue_token(client)},
            REMOTE_ADDR=f"203.0.113.{index}",
        )
        assert response.status_code == 201

    assert DealEvidenceEvent.objects.count() == 2
    assert Client().get("/api/v2/deals").json()["venues"][0]["deals"] == []


@pytest.mark.django_db
def test_corroborated_canonical_deal_publishes_only_trusted_text_and_structured_values():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    common = {
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "action": "ADD_MISSING",
        "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
        "submittedDealShape": {
            "canonicalFamilyId": str(family.id),
            "displayName": "Unreviewed user-authored label",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 500,
            "unit": "Unreviewed user-authored unit",
            "servingFormat": "Unreviewed user-authored serving",
            "timingKnown": True,
            "timingDescription": "Unreviewed user-authored timing",
        },
    }

    for index in (1, 2):
        client = Client()
        response = client.post(
            "/api/v2/deal-evidence",
            data={**common, "submissionId": str(uuid.uuid4())},
            content_type="application/json",
            headers={"X-Installation-Token": issue_token(client)},
            REMOTE_ADDR=f"203.0.113.{index}",
        )
        assert response.status_code == 201

    public_deal = Client().get("/api/v2/deals").json()["venues"][0]["deals"][0]
    assert public_deal["canonicalFamilyId"] == str(family.id)
    assert public_deal["displayName"] == "Wells"
    assert public_deal["category"] == "drink"
    assert public_deal["priceCents"] == 500
    assert public_deal["unit"] == ""
    assert public_deal["servingFormat"] == ""
    assert public_deal["timingDescription"] is None
    assert public_deal["timingKnown"] is False


@pytest.mark.django_db
def test_corroborated_correction_keeps_structured_price_but_not_replacement_text():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    deal = DealDefinition.objects.create(
        venue=venue,
        display_name="Wells",
        category="drink",
        price_kind="single",
        price_cents=500,
        unit="shot",
        serving_format="glass",
        timing_description="All night",
        timing_known=True,
    )
    correction_client = Client()
    correction = correction_client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CORRECT",
            "targetDealId": str(deal.id),
            "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
            "submittedDealShape": {
                "displayName": "Unreviewed replacement label",
                "category": "food",
                "priceKind": "single",
                "priceCents": 600,
                "unit": "Unreviewed replacement unit",
                "servingFormat": "Unreviewed replacement serving",
                "timingKnown": True,
                "timingDescription": "Unreviewed replacement timing",
            },
        },
        content_type="application/json",
        headers={"X-Installation-Token": issue_token(correction_client)},
        REMOTE_ADDR="203.0.113.1",
    )
    assert correction.status_code == 201

    confirmation_client = Client()
    confirmation = confirmation_client.post(
        "/api/v2/deal-evidence",
        data={
            "submissionId": str(uuid.uuid4()),
            "venueId": str(venue.id),
            "observedAt": timezone.now().isoformat(),
            "action": "CONFIRM_PRESENT",
            "targetDealId": correction.json()["eventId"],
            "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
        },
        content_type="application/json",
        headers={"X-Installation-Token": issue_token(confirmation_client)},
        REMOTE_ADDR="203.0.113.2",
    )
    assert confirmation.status_code == 201

    public_deal = Client().get("/api/v2/deals").json()["venues"][0]["deals"][0]
    assert public_deal["displayName"] == "Wells"
    assert public_deal["category"] == "drink"
    assert public_deal["priceCents"] == 600
    assert public_deal["unit"] == ""
    assert public_deal["servingFormat"] == ""
    assert public_deal["timingDescription"] is None
    assert public_deal["timingKnown"] is False


@pytest.mark.django_db
def test_two_independent_identical_canonical_adds_corroborate_without_sharing_event_id():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    common = {
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "action": "ADD_MISSING",
        "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
        "submittedDealShape": {
            "canonicalFamilyId": str(family.id),
            "displayName": "$5 wells",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 500,
        },
    }

    for index in (1, 2):
        client = Client()
        token = issue_token(client)
        response = client.post(
            "/api/v2/deal-evidence",
            data={**common, "submissionId": str(uuid.uuid4())},
            content_type="application/json",
            headers={"X-Installation-Token": token},
            REMOTE_ADDR=f"203.0.113.{index}",
        )
        assert response.status_code == 201

    deals = Client().get("/api/v2/deals").json()["venues"][0]["deals"]
    assert len(deals) == 1
    assert deals[0]["displayName"] == "Wells"


@pytest.mark.django_db
def test_unresolved_custom_deal_keeps_leading_dollar_name_only_in_private_evidence():
    venue = Venue.objects.create(slug="sandwiches", name="Sandwiches")
    common = {
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "action": "ADD_MISSING",
        "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
        "submittedDealShape": {
            "displayName": "$5 Footlongs",
            "category": "food",
            "priceKind": "single",
            "priceCents": 600,
        },
    }

    for index in (1, 2):
        client = Client()
        response = client.post(
            "/api/v2/deal-evidence",
            data={**common, "submissionId": str(uuid.uuid4())},
            content_type="application/json",
            headers={"X-Installation-Token": issue_token(client)},
            REMOTE_ADDR=f"203.0.113.{index}",
        )
        assert response.status_code == 201

    stored = list(DealEvidenceEvent.objects.values_list("submitted_deal_shape", flat=True))
    deals = Client().get("/api/v2/deals").json()["venues"][0]["deals"]
    assert len(stored) == 2
    assert all(shape["displayName"] == "$5 Footlongs" for shape in stored)
    assert deals == []


@pytest.mark.django_db
def test_same_installation_switching_networks_is_still_one_deal_vote():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    token = issue_token(client)
    common = {
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "action": "ADD_MISSING",
        "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
        "submittedDealShape": {
            "displayName": "$5 wells",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 500,
        },
    }

    for address in ("203.0.113.1", "203.0.113.2"):
        response = client.post(
            "/api/v2/deal-evidence",
            data={**common, "submissionId": str(uuid.uuid4())},
            content_type="application/json",
            headers={"X-Installation-Token": token},
            REMOTE_ADDR=address,
        )
        assert response.status_code == 201

    assert client.get("/api/v2/deals").json()["venues"][0]["deals"] == []


@pytest.mark.django_db
def test_guest_then_linked_account_session_is_still_one_installation_vote():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    client = Client()
    installation_token = issue_token(client)
    actor = InstallationActor.objects.get()
    observed_at = timezone.now()
    common = {
        "venueId": str(venue.id),
        "observedAt": observed_at.isoformat(),
        "action": "ADD_MISSING",
        "serviceDateLocal": service_date_for(observed_at).isoformat(),
        "submittedDealShape": {
            "displayName": "$5 wells",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 500,
        },
    }

    guest = client.post(
        "/api/v2/deal-evidence",
        data={**common, "submissionId": str(uuid.uuid4())},
        content_type="application/json",
        headers={"X-Installation-Token": installation_token},
        REMOTE_ADDR="203.0.113.1",
    )
    account = Account.objects.create_user("linked-voter@example.com")
    ActorAccountLink.objects.create(actor=actor, account=account)
    session = SessionStore()
    session[SESSION_KEY] = str(account.pk)
    session.save()
    account_session_token = issue_session_token(session)
    signed_in = client.post(
        "/api/v2/deal-evidence",
        data={**common, "submissionId": str(uuid.uuid4())},
        content_type="application/json",
        headers={
            "X-Installation-Token": installation_token,
            "X-Session-Token": account_session_token,
        },
        REMOTE_ADDR="203.0.113.2",
    )

    account_ids = list(
        DealEvidenceEvent.objects.order_by("created_at").values_list(
            "submission__private_context__account_id", flat=True
        )
    )
    assert guest.status_code == 201
    assert signed_in.status_code == 201
    assert account_ids == [None, account.pk]
    assert client.get("/api/v2/deals").json()["venues"][0]["deals"] == []


@pytest.mark.django_db
def test_two_guest_installations_on_one_network_do_not_mutate_public_slate():
    venue = Venue.objects.create(slug="kams", name="KAMS")
    common = {
        "venueId": str(venue.id),
        "observedAt": timezone.now().isoformat(),
        "action": "ADD_MISSING",
        "serviceDateLocal": service_date_for(timezone.now()).isoformat(),
        "submittedDealShape": {
            "displayName": "$5 wells",
            "category": "drink",
            "priceKind": "single",
            "priceCents": 500,
        },
    }

    for _ in range(2):
        client = Client()
        token = issue_token(client)
        response = client.post(
            "/api/v2/deal-evidence",
            data={**common, "submissionId": str(uuid.uuid4())},
            content_type="application/json",
            headers={"X-Installation-Token": token},
            REMOTE_ADDR="203.0.113.1",
        )
        assert response.status_code == 201

    assert Client().get("/api/v2/deals").json()["venues"][0]["deals"] == []


@pytest.mark.django_db
def test_deal_release_receipt_is_immutable_and_external_dataset_is_not_predicted():
    from deals.predictor import (
        build_selected_prediction_release,
        materialize_predictions,
        promote_prediction_release,
    )

    venue = Venue.objects.create(slug="kams", name="KAMS")
    DatasetRelease.objects.create(
        name="historical-deals-v1",
        content_hash="a0c9222cb5a268001657adc679c13c36232aa1bbc10856144c8e68aa91e7e6dd",
        schema_version="1",
        importer_version="test",
    )
    family = DealFamily.objects.create(canonical_name="Foreign", category="drink")
    target = timezone.localdate()
    for offset in (7, 14):
        fact_date = target - timedelta(days=offset)
        HistoricalDealFact.objects.create(
            source_record_key=f"foreign-{offset}",
            source_dataset="unselected-future-release",
            venue=venue,
            family=family,
            display_name="$1 foreign",
            category="drink",
            price_kind="single",
            price_cents=100,
            service_date_local=fact_date,
            timing_kind="unknown",
            source_post_key=f"foreign-{offset}",
            source_payload_hash="f" * 64,
        )

    release = promote_prediction_release(build_selected_prediction_release())
    selected, created = materialize_predictions(target)

    assert selected == release
    assert created == 0
    assert not DealPrediction.objects.filter(release=release).exists()
    release.parameters = {"tampered": True}
    with pytest.raises(ValidationError, match="immutable"):
        release.save()
    external_fact = HistoricalDealFact.objects.get(source_record_key="foreign-7")
    external_fact.display_name = "tampered"
    with pytest.raises(ValidationError, match="immutable"):
        external_fact.save()


@pytest.mark.django_db
def test_materialization_fails_closed_without_resurrecting_a_retired_deal_release():
    from deals.predictor import DealPredictionLifecycleError, materialize_predictions

    training_revision = "a0c9222cb5a268001657adc679c13c36232aa1bbc10856144c8e68aa91e7e6dd"
    DatasetRelease.objects.create(
        name="historical-deals-v1",
        content_hash=training_revision,
        schema_version="1",
        importer_version="test",
    )
    first_promotion = timezone.now() - timedelta(days=2)
    retirement = timezone.now() - timedelta(days=1)
    retired = DealPredictionRelease.objects.create(
        predictor_version="deal_recurrence_v1",
        code_revision="retired-code",
        training_data_revision=training_revision,
        parameters={"release": "retired"},
        evaluation_metrics={"status": "accepted"},
        promoted_at=first_promotion,
        retired_at=retirement,
    )
    current = DealPredictionRelease.objects.create(
        predictor_version="deal_recurrence_v2",
        code_revision="current-code",
        training_data_revision="current-training-revision",
        parameters={"release": "current"},
        evaluation_metrics={"status": "accepted"},
        is_authoritative=True,
        promoted_at=retirement,
    )

    with pytest.raises(
        DealPredictionLifecycleError,
        match="No materializer is available for deal predictor 'deal_recurrence_v2'",
    ):
        materialize_predictions(service_date_for(timezone.now()))

    retired.refresh_from_db()
    current.refresh_from_db()
    assert not DealPrediction.objects.exists()
    assert retired.is_authoritative is False
    assert retired.promoted_at == first_promotion
    assert retired.retired_at == retirement
    assert current.is_authoritative is True
    assert current.promoted_at == retirement
    assert current.retired_at is None


@pytest.mark.django_db
def test_predictor_materializes_deterministic_positive_ranks_as_immutable_artifacts():
    from deals.predictor import (
        build_selected_prediction_release,
        materialize_predictions,
        promote_prediction_release,
    )

    venue = Venue.objects.create(slug="kams", name="KAMS")
    DatasetRelease.objects.create(
        name="historical-deals-v1",
        content_hash="a0c9222cb5a268001657adc679c13c36232aa1bbc10856144c8e68aa91e7e6dd",
        schema_version="1",
        importer_version="test",
    )
    target = service_date_for(timezone.now())
    families = {
        "strong": DealFamily.objects.create(canonical_name="Strong", category="drink"),
        "weaker": DealFamily.objects.create(canonical_name="Weaker", category="drink"),
    }
    for family_name, offsets in (("strong", (7, 14, 21)), ("weaker", (7, 14))):
        for offset in offsets:
            fact_date = target - timedelta(days=offset)
            HistoricalDealFact.objects.create(
                source_record_key=f"{family_name}-{offset}",
                source_dataset="historical-deals-v1",
                venue=venue,
                family=families[family_name],
                display_name=family_name.title(),
                category="drink",
                price_kind="single",
                price_cents=500,
                service_date_local=fact_date,
                timing_kind="unknown",
                source_post_key=f"{family_name}-{offset}",
                source_payload_hash=family_name[0] * 64,
            )

    release = promote_prediction_release(build_selected_prediction_release())
    selected, created = materialize_predictions(target)
    predictions = list(
        DealPrediction.objects.filter(release=release)
        .select_related("deal_definition__family")
        .order_by("rank")
    )

    assert selected == release
    assert created == 2
    assert [(row.rank, row.deal_definition.family.canonical_name) for row in predictions] == [
        (1, "Strong"),
        (2, "Weaker"),
    ]
    predictions[0].rank = 3
    with pytest.raises(ValidationError, match="immutable"):
        predictions[0].save()


@pytest.mark.django_db
def test_predictor_materializes_distinct_serving_and_timing_offer_identities():
    from deals.predictor import _receipt, materialize_predictions

    venue = Venue.objects.create(slug="kams", name="KAMS")
    training_revision = "a0c9222cb5a268001657adc679c13c36232aa1bbc10856144c8e68aa91e7e6dd"
    DatasetRelease.objects.create(
        name="historical-deals-v1",
        content_hash=training_revision,
        schema_version="1",
        importer_version="test",
    )
    receipt = _receipt()
    release = DealPredictionRelease.objects.create(
        predictor_version="deal_recurrence_v1",
        code_revision="test",
        training_data_revision=training_revision,
        parameters=receipt["model_release"]["prediction_contract"],
        evaluation_metrics=receipt["model_release"]["selected_backtest"],
        is_authoritative=True,
        promoted_at=timezone.now(),
    )
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    target = service_date_for(timezone.now())
    for offset in (7, 14):
        service_date = target - timedelta(days=offset)
        HistoricalDealFact.objects.create(
            source_record_key=f"pitcher-{offset}",
            source_dataset="historical-deals-v1",
            venue=venue,
            family=family,
            display_name="Wells",
            category="drink",
            price_kind="single",
            price_cents=500,
            unit="pitcher",
            service_date_local=service_date,
            timing_kind="between_times",
            timing_start_local=time(21),
            timing_end_local=time(23),
            source_post_key=f"pitcher-post-{offset}",
            source_payload_hash="a" * 64,
        )
        HistoricalDealFact.objects.create(
            source_record_key=f"shot-{offset}",
            source_dataset="historical-deals-v1",
            venue=venue,
            family=family,
            display_name="Wells",
            category="drink",
            price_kind="single",
            price_cents=300,
            unit="shot",
            service_date_local=service_date,
            timing_kind="all_night",
            source_post_key=f"shot-post-{offset}",
            source_payload_hash="b" * 64,
        )

    selected, created = materialize_predictions(target)
    materialized = {
        (
            prediction.deal_definition.unit,
            prediction.deal_definition.serving_format,
            prediction.deal_definition.timing_description,
        )
        for prediction in DealPrediction.objects.filter(release=release).select_related(
            "deal_definition"
        )
    }

    assert selected == release
    assert created == 2
    assert materialized == {
        ("pitcher", "pitcher", "9 PM–11 PM"),
        ("shot", "shot", "All night"),
    }


@pytest.mark.django_db
def test_nightly_refresh_materializes_the_current_authoritative_deal_release():
    from deals.predictor import _receipt

    venue = Venue.objects.create(slug="kams", name="KAMS")
    training_revision = "a0c9222cb5a268001657adc679c13c36232aa1bbc10856144c8e68aa91e7e6dd"
    DatasetRelease.objects.create(
        name="historical-deals-v1",
        content_hash=training_revision,
        schema_version="1",
        importer_version="test",
    )
    receipt = _receipt()
    current = DealPredictionRelease.objects.create(
        predictor_version="deal_recurrence_v1_recovery",
        code_revision="current-code",
        training_data_revision=training_revision,
        parameters={
            **receipt["model_release"]["prediction_contract"],
            "implementation": "deal_recurrence_v1",
        },
        evaluation_metrics={"status": "accepted"},
        is_authoritative=True,
        promoted_at=timezone.now(),
    )
    family = DealFamily.objects.create(canonical_name="Wells", category="drink")
    target = service_date_for(timezone.now())
    for offset in (7, 14):
        HistoricalDealFact.objects.create(
            source_record_key=f"current-{offset}",
            source_dataset="historical-deals-v1",
            venue=venue,
            family=family,
            display_name="Wells",
            category="drink",
            price_kind="single",
            price_cents=500,
            service_date_local=target - timedelta(days=offset),
            timing_kind="unknown",
            source_post_key=f"current-post-{offset}",
            source_payload_hash="c" * 64,
        )

    call_command("refresh_deal_predictions", service_date=target, verbosity=0)

    assert DealPredictionRelease.objects.count() == 1
    assert DealPrediction.objects.filter(release=current, service_date_local=target).count() == 1
