import json
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_DIR = Path(__file__).resolve().parents[3]


def production_environment(deployment_environment: str | None) -> dict[str, str]:
    secrets = {
        "DATABASE_URL": (
            "postgresql://probe:probe@127.0.0.1/probe"
            "?sslmode=verify-full"
            "&sslrootcert=/etc/ssl/certs/ca-certificates.crt"
            "&channel_binding=require"
        ),
        "DJANGO_SECRET_KEY": "production-host-test-secret",
    }
    environment = {
        "CODE_REVISION": "src-production-host-test",
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "ILLINICOVER_SECRETS_JSON": json.dumps(secrets),
        "PUBLIC_API_ORIGIN": "https://illinicover-api-1068900473446.us-east5.run.app",
        "PYTHONPATH": str(REPOSITORY_DIR / "server"),
    }
    if deployment_environment is not None:
        environment["DEPLOYMENT_ENVIRONMENT"] = deployment_environment
    # Preserve platform variables needed to launch the current interpreter.
    for name in ("PATH", "DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH", "SYSTEMROOT"):
        if value := os.environ.get(name):
            environment[name] = value
    return environment


def test_production_liveness_accepts_public_and_probe_hosts_only():
    script = """
import django

django.setup()

from django.conf import settings
from django.test import Client

expected_hosts = [
    ".run.app",
    "api.illinicover.com",
    "localhost",
    "127.0.0.1",
]
assert settings.ALLOWED_HOSTS == expected_hosts
assert settings.DEPLOYMENT_ENVIRONMENT == "production"
assert settings.SENTRY_ENVIRONMENT == "production"
assert settings.DATABASES["default"]["OPTIONS"] == {
    "sslmode": "verify-full",
    "sslrootcert": "/etc/ssl/certs/ca-certificates.crt",
    "channel_binding": "require",
}

client = Client()
for host in (
    "illinicover-api-1068900473446.us-east5.run.app",
    "api.illinicover.com",
    "localhost",
    "127.0.0.1",
):
    response = client.get("/health/live", secure=True, HTTP_HOST=host)
    assert response.status_code == 200, (host, response.status_code)

response = client.get("/health/live", secure=True, HTTP_HOST="attacker.invalid")
assert response.status_code == 400
"""
    environment = production_environment("production")

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_production_settings_fail_closed_without_a_deployment_environment():
    completed = subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=REPOSITORY_DIR,
        env=production_environment(None),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "DEPLOYMENT_ENVIRONMENT must be production or preview" in completed.stderr


def test_preview_sentry_uses_the_deployment_environment():
    script = """
import config.monitoring

captured = {}
config.monitoring.configure_sentry = lambda **kwargs: captured.update(kwargs)

import django
django.setup()

from django.conf import settings

assert settings.DEPLOYMENT_ENVIRONMENT == "preview"
assert settings.SENTRY_ENVIRONMENT == "preview"
assert captured["environment"] == "preview"
"""
    environment = production_environment("preview")
    secrets = json.loads(environment["ILLINICOVER_SECRETS_JSON"])
    secrets["SENTRY_DSN"] = "https://public@example.invalid/1"
    environment["ILLINICOVER_SECRETS_JSON"] = json.dumps(secrets)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
