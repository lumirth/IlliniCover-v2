import secrets

import pytest
from identity.credentials import INSTALLATION_TOKEN_PREFIX, installation_verifier

from product.models import InstallationActor, Venue


@pytest.fixture
def venue(db):
    return Venue.objects.create(slug="kams", name="KAMS", latitude=40.11044, longitude=-88.23825)


@pytest.fixture
def installation(db):
    token = INSTALLATION_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, InstallationActor.objects.create(verifier=installation_verifier(token))
