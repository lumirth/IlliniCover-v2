#!/usr/bin/env python3
"""Delete one OCI image index, its child manifests, and its attachments."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Protocol
from urllib.parse import quote

DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*")
MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


class ManifestRegistry(Protocol):
    def manifest(self, digest: str) -> Mapping[str, object] | None: ...

    def attachments(self, digest: str) -> tuple[str, ...]: ...

    def delete_attachment(self, name: str) -> None: ...

    def delete_manifest(self, digest: str) -> None: ...


class GcloudRegistry:
    """Artifact Registry metadata boundary; never downloads image layers."""

    def __init__(
        self,
        *,
        project: str,
        location: str,
        repository: str,
        package: str,
    ) -> None:
        for label, value in (
            ("project", project),
            ("location", location),
            ("repository", repository),
        ):
            if NAME_PATTERN.fullmatch(value) is None:
                raise ValueError(f"invalid Artifact Registry {label}: {value!r}")
        if NAME_PATTERN.fullmatch(package) is None:
            raise ValueError(f"invalid Artifact Registry package: {package!r}")
        self.project = project
        self.location = location
        self.repository = repository
        self.package = package
        self.host = f"{location}-docker.pkg.dev"
        self.image = f"{self.host}/{project}/{repository}/{package}"
        self.version_prefix = (
            f"projects/{project}/locations/{location}/repositories/{repository}/"
            f"packages/{package}/versions"
        )
        self._token: str | None = None

    def _gcloud(self, *arguments: str) -> str:
        return subprocess.run(
            ["gcloud", *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def _access_token(self) -> str:
        if self._token is None:
            self._token = self._gcloud("auth", "print-access-token").strip()
            if not self._token:
                raise RuntimeError("gcloud returned an empty access token")
        return self._token

    def manifest(self, digest: str) -> Mapping[str, object] | None:
        _validate_digest(digest)
        image_path = quote(
            f"{self.project}/{self.repository}/{self.package}",
            safe="/",
        )
        url = f"https://{self.host}/v2/{image_path}/manifests/{digest}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Accept": MANIFEST_ACCEPT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise RuntimeError(
                f"Artifact Registry manifest lookup failed: HTTP {error.code}"
            ) from error
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Artifact Registry manifest lookup failed: {error}") from error
        if not isinstance(payload, dict):
            raise RuntimeError("Artifact Registry returned a non-object manifest")
        return payload

    def attachments(self, digest: str) -> tuple[str, ...]:
        _validate_digest(digest)
        output = self._gcloud(
            "artifacts",
            "attachments",
            "list",
            "--project",
            self.project,
            "--location",
            self.location,
            "--repository",
            self.repository,
            "--target",
            f"{self.version_prefix}/{digest}",
            "--format=json",
        )
        payload = json.loads(output)
        if not isinstance(payload, list):
            raise RuntimeError("Artifact Registry returned a non-list attachment inventory")
        names = []
        expected_prefix = (
            f"projects/{self.project}/locations/{self.location}/repositories/"
            f"{self.repository}/attachments/"
        )
        for item in payload:
            name = item.get("name") if isinstance(item, dict) else None
            if not isinstance(name, str) or not name.startswith(expected_prefix):
                raise RuntimeError("Artifact Registry returned an invalid attachment name")
            names.append(name)
        return tuple(sorted(names))

    def delete_attachment(self, name: str) -> None:
        self._gcloud(
            "artifacts",
            "attachments",
            "delete",
            name,
            "--project",
            self.project,
            "--quiet",
        )

    def delete_manifest(self, digest: str) -> None:
        _validate_digest(digest)
        if self.manifest(digest) is None:
            return
        self._gcloud(
            "artifacts",
            "docker",
            "images",
            "delete",
            f"{self.image}@{digest}",
            "--project",
            self.project,
            "--delete-tags",
            "--quiet",
        )


def _validate_digest(digest: str) -> None:
    if DIGEST_PATTERN.fullmatch(digest) is None:
        raise ValueError(f"{digest!r} is not a valid sha256 digest")


def cleanup_image(
    registry: ManifestRegistry,
    root_digest: str,
    *,
    execute: bool,
) -> tuple[str, ...]:
    """Plan, optionally delete, and verify one complete OCI manifest closure."""

    planned: list[str] = []
    deletion_order: list[str] = []

    def visit(digest: str) -> None:
        _validate_digest(digest)
        if digest in planned:
            return
        planned.append(digest)
        manifest = registry.manifest(digest)
        if manifest is None:
            deletion_order.append(digest)
            return
        children = manifest.get("manifests", [])
        if not isinstance(children, list):
            raise ValueError(f"manifest {digest} has an invalid child list")
        for descriptor in children:
            if not isinstance(descriptor, dict) or not isinstance(descriptor.get("digest"), str):
                raise ValueError(f"manifest {digest} has an invalid child descriptor")
            visit(descriptor["digest"])
        deletion_order.append(digest)

    visit(root_digest)
    if not execute:
        return tuple(planned)
    attachments = tuple(
        dict.fromkeys(
            attachment
            for digest in planned
            for attachment in registry.attachments(digest)
        )
    )
    for attachment in attachments:
        registry.delete_attachment(attachment)
    remaining_attachments = {}
    for digest in planned:
        remaining = registry.attachments(digest)
        if remaining:
            remaining_attachments[digest] = remaining
    if remaining_attachments:
        raise RuntimeError(
            "artifact attachments remain after cleanup: "
            + ", ".join(
                attachment
                for names in remaining_attachments.values()
                for attachment in names
            )
        )
    for digest in deletion_order:
        registry.delete_manifest(digest)
    remaining_manifests = [
        digest for digest in planned if registry.manifest(digest) is not None
    ]
    if remaining_manifests:
        raise RuntimeError(
            "artifact manifests remain addressable after cleanup: "
            + ", ".join(remaining_manifests)
        )
    return tuple(planned)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete and verify one complete Artifact Registry OCI image closure."
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform deletion; otherwise print the manifest plan only.",
    )
    args = parser.parse_args()
    try:
        registry = GcloudRegistry(
            project=args.project,
            location=args.location,
            repository=args.repository,
            package=args.package,
        )
        manifests = cleanup_image(registry, args.digest, execute=args.execute)
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        ValueError,
    ) as error:
        print(f"artifact image cleanup failed: {error}", file=sys.stderr)
        return 3
    if args.execute:
        print(f"Cleaned and verified {len(manifests)} OCI manifest target(s).")
    else:
        print(json.dumps({"manifests": manifests}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
