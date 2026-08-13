from django.test import RequestFactory, override_settings
from identity.adapters import IlliniCoverAccountAdapter

from config.network import client_address


@override_settings(TRUSTED_XFF_PROXY_HOPS=1)
def test_client_address_uses_trusted_suffix_not_spoofable_xff_prefix():
    request = RequestFactory().get(
        "/api/v2/cover",
        HTTP_X_FORWARDED_FOR="198.51.100.250, 203.0.113.8, 192.0.2.10",
        REMOTE_ADDR="127.0.0.1",
    )

    assert client_address(request) == "203.0.113.8"


def test_client_address_falls_back_to_validated_remote_address():
    request = RequestFactory().get("/api/v2/cover", REMOTE_ADDR="203.0.113.20")

    assert client_address(request) == "203.0.113.20"


@override_settings(TRUSTED_XFF_PROXY_HOPS=1, NETWORK_METADATA_PEPPER="rate-test-pepper")
def test_allauth_uses_distinct_keyed_network_identities_not_spoofed_or_raw_addresses():
    factory = RequestFactory()
    first = factory.get(
        "/_allauth/app/v1/auth/code/request",
        HTTP_X_FORWARDED_FOR="198.51.100.250, 203.0.113.8, 192.0.2.10",
    )
    same_client_spoofed = factory.get(
        "/_allauth/app/v1/auth/code/request",
        HTTP_X_FORWARDED_FOR="198.51.100.99, 203.0.113.8, 192.0.2.10",
    )
    second = factory.get(
        "/_allauth/app/v1/auth/code/request",
        HTTP_X_FORWARDED_FOR="198.51.100.250, 203.0.113.9, 192.0.2.10",
    )
    adapter = IlliniCoverAccountAdapter()

    first_key = adapter.get_client_ip(first)

    assert first_key == adapter.get_client_ip(same_client_spoofed)
    assert first_key != adapter.get_client_ip(second)
    assert "203.0.113.8" not in first_key
    assert first_key.startswith("ic_network_")
