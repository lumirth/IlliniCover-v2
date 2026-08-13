import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection
from django.test import Client, override_settings

from identity.models import IdentityRateBucket, InstallationActor, InstallationOperationReceipt


def _post_create(barrier: Barrier, payload: dict, address: str):
    close_old_connections()
    try:
        barrier.wait(timeout=5)
        response = Client().post(
            "/api/v2/installations",
            data=payload,
            content_type="application/json",
            REMOTE_ADDR=address,
        )
        return response.status_code, response.json()
    finally:
        close_old_connections()


@pytest.mark.django_db(transaction=True)
def test_concurrent_equal_installation_request_returns_one_actor_and_one_result():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL advisory-lock acceptance test")
    payload = {
        "requestId": str(uuid.uuid4()),
        "installationToken": "ic_install_" + "a" * 43,
    }
    barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: _post_create(barrier, payload, "203.0.113.20"),
                range(2),
            )
        )

    assert [status for status, _ in results] == [201, 201]
    assert results[0][1] == results[1][1]
    assert InstallationActor.objects.count() == 1
    assert InstallationOperationReceipt.objects.count() == 1
    assert IdentityRateBucket.objects.get().count == 1


@pytest.mark.django_db(transaction=True)
@override_settings(INSTALLATION_ISSUANCE_RATE_LIMIT=(1, 3600))
def test_concurrent_network_limit_never_issues_more_than_the_bound():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock acceptance test")
    payloads = [
        {
            "requestId": str(uuid.uuid4()),
            "installationToken": "ic_install_" + character * 43,
        }
        for character in ("a", "b")
    ]
    barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_post_create, barrier, payload, "203.0.113.21")
            for payload in payloads
        ]
        results = [future.result() for future in futures]

    assert sorted(status for status, _ in results) == [201, 429]
    assert InstallationActor.objects.count() == 1
    assert IdentityRateBucket.objects.get().count == 1
