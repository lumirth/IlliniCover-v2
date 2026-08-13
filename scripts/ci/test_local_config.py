from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPOSITORY = Path(__file__).resolve().parents[2]


def dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


class LocalConfigurationTests(unittest.TestCase):
    def test_compose_is_postgresql_only_and_matches_example_credentials(self) -> None:
        compose = yaml.safe_load((REPOSITORY / "compose.yaml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(set(services), {"postgres"})
        postgres = services["postgres"]
        self.assertRegex(postgres["image"], r"^postgres:18\.4-bookworm@sha256:[0-9a-f]{64}$")
        self.assertEqual(postgres["ports"], ["127.0.0.1:5432:5432"])

        example = dotenv(REPOSITORY / ".env.example")
        configured = urlparse(example["DATABASE_URL"])
        self.assertEqual(configured.hostname, "127.0.0.1")
        self.assertEqual(configured.port, 5432)
        self.assertEqual(configured.path.removeprefix("/"), postgres["environment"]["POSTGRES_DB"])
        self.assertEqual(configured.username, postgres["environment"]["POSTGRES_USER"])
        self.assertEqual(configured.password, postgres["environment"]["POSTGRES_PASSWORD"])
        self.assertEqual(example["DATABASE_URL_DIRECT"], example["DATABASE_URL"])

    def test_local_fallback_matches_the_checked_in_example(self) -> None:
        example = dotenv(REPOSITORY / ".env.example")
        environment_script = (REPOSITORY / "scripts/local/environment.sh").read_text(
            encoding="utf-8"
        )
        match = re.search(r'DATABASE_URL:-([^}"]+)', environment_script)
        if match is None:
            self.fail("scripts/local/environment.sh has no DATABASE_URL fallback")
        self.assertEqual(match.group(1), example["DATABASE_URL"])

    def test_example_is_safe_to_source_after_clean_setup_copy(self) -> None:
        result = subprocess.run(
            [
                "bash",
                "-c",
                'set -eu; set -a; source "$1"; set +a; test -n "$DEFAULT_FROM_EMAIL"',
                "bash",
                str(REPOSITORY / ".env.example"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_toolchain_pins_python_uv_and_gcloud(self) -> None:
        mise = (REPOSITORY / "mise.toml").read_text(encoding="utf-8")
        self.assertRegex(mise, r'(?m)^python = "3\.14\.7"$')
        self.assertRegex(mise, r'(?m)^uv = "0\.9\.3"$')
        self.assertRegex(mise, r'(?m)^gcloud = "580\.0\.0"$')
        self.assertRegex(mise, r'(?m)^actionlint = "1\.7\.12"$')

    def test_local_compose_wrapper_pins_project_and_file(self) -> None:
        wrapper = (REPOSITORY / "scripts/local/compose.sh").read_text(encoding="utf-8")
        self.assertIn('project_name="illinicover-v2-local"', wrapper)
        self.assertIn('--project-name "$project_name"', wrapper)
        self.assertIn('--file "$compose_file"', wrapper)
        for script_name in (
            "setup.sh",
            "up.sh",
            "test-server.sh",
            "doctor.sh",
            "reset-database.sh",
        ):
            script = (REPOSITORY / "scripts/local" / script_name).read_text(encoding="utf-8")
            self.assertNotIn("docker compose", script)


if __name__ == "__main__":
    unittest.main()
