#!/usr/bin/env python3
"""Project the exact Cloud Run state needed for release rollback."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any

DIGEST_IMAGE_PATTERN = re.compile(r".+@sha256:[0-9a-f]{64}")
RESOURCE_NAME_PATTERN = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")
TOP_LEVEL_ANNOTATION_NOISE = frozenset(
    {
        "run.googleapis.com/client-name",
        "run.googleapis.com/client-version",
        "run.googleapis.com/creator",
        "run.googleapis.com/lastModifier",
        "run.googleapis.com/operation-id",
        "serving.knative.dev/creator",
        "serving.knative.dev/lastModifier",
    }
)
TOP_LEVEL_LABEL_NOISE = frozenset(
    {
        "client.knative.dev/nonce",
        "cloud.googleapis.com/location",
        "run.googleapis.com/lastUpdatedTime",
        "run.googleapis.com/satisfiesPzi",
        "run.googleapis.com/satisfiesPzs",
    }
)


def _resource_names(resources: object) -> tuple[str, ...]:
    if not isinstance(resources, list):
        raise ValueError("Cloud Run discovery requires a JSON list")
    names: list[str] = []
    for item in resources:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if not isinstance(name, str) or RESOURCE_NAME_PATTERN.fullmatch(name) is None:
            raise ValueError("Cloud Run resource is missing exact metadata.name")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("Cloud Run returned duplicate resource metadata")
    return tuple(sorted(names))


def discover_resource(resources: object, name: str) -> str:
    """Return PRESENT or ABSENT from one successfully loaded inventory."""

    return "PRESENT" if name in _resource_names(resources) else "ABSENT"


def _container_images(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        candidate = value.get("containers")
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, dict) and isinstance(item.get("image"), str):
                    yield item["image"]
        for child in value.values():
            yield from _container_images(child)
    elif isinstance(value, list):
        for child in value:
            yield from _container_images(child)


def resource_image(resource: object) -> str:
    """Return the resource's single exact digest-pinned container image."""

    images = tuple(dict.fromkeys(_container_images(resource)))
    if len(images) != 1 or DIGEST_IMAGE_PATTERN.fullmatch(images[0]) is None:
        raise ValueError("Cloud Run resource must have one digest-pinned container image")
    return images[0]


def _functional_metadata(metadata: dict[str, Any], name: str) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name}
    for field, noise in (
        ("annotations", TOP_LEVEL_ANNOTATION_NOISE),
        ("labels", TOP_LEVEL_LABEL_NOISE),
    ):
        value = metadata.get(field)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"Cloud Run job metadata.{field} must be a JSON object")
        filtered = {key: deepcopy(item) for key, item in value.items() if key not in noise}
        if filtered:
            result[field] = filtered
    return result


def _job_parts(resource: object) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(resource, dict):
        raise ValueError("Cloud Run job must be a JSON object")
    metadata = resource.get("metadata")
    name = metadata.get("name") if isinstance(metadata, dict) else None
    spec = resource.get("spec")
    if (
        not isinstance(metadata, dict)
        or not isinstance(name, str)
        or RESOURCE_NAME_PATTERN.fullmatch(name) is None
    ):
        raise ValueError("Cloud Run job is missing exact metadata.name")
    if not isinstance(spec, dict) or not isinstance(spec.get("template"), dict):
        raise ValueError("Cloud Run job is missing its runtime spec")
    return _functional_metadata(metadata, name), deepcopy(spec)


def job_config(resource: object) -> dict[str, Any]:
    """Return the complete functional job spec used for rollback comparison."""

    metadata, spec = _job_parts(resource)
    template_metadata = spec.get("template", {}).get("metadata")
    if isinstance(template_metadata, dict):
        annotations = template_metadata.get("annotations")
        labels = template_metadata.get("labels")
        if isinstance(annotations, dict):
            for key in (
                "run.googleapis.com/client-name",
                "run.googleapis.com/client-version",
            ):
                annotations.pop(key, None)
            if not annotations:
                template_metadata.pop("annotations", None)
        if isinstance(labels, dict):
            labels.pop("client.knative.dev/nonce", None)
            if not labels:
                template_metadata.pop("labels", None)
        if not template_metadata:
            spec["template"].pop("metadata", None)
    return {"metadata": metadata, "spec": spec}


def job_replace_manifest(resource: object) -> dict[str, Any]:
    """Return a bounded replace manifest containing only functional job state."""

    config = job_config(resource)
    return {
        "apiVersion": "run.googleapis.com/v1",
        "kind": "Job",
        "metadata": config["metadata"],
        "spec": config["spec"],
    }


def revision_names(resources: object) -> tuple[str, ...]:
    return _resource_names(resources)


def new_image_revisions(
    resources: object,
    *,
    image: str,
    baseline: set[str],
) -> tuple[str, ...]:
    """Select only post-snapshot revisions that pin the exact release image."""

    if DIGEST_IMAGE_PATTERN.fullmatch(image) is None:
        raise ValueError("release image must be digest-pinned")
    if not isinstance(resources, list):
        raise ValueError("Cloud Run revision discovery requires a JSON list")
    names = revision_names(resources)
    by_name: dict[str, object] = {}
    for item in resources:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if not isinstance(name, str) or RESOURCE_NAME_PATTERN.fullmatch(name) is None:
            raise ValueError("Cloud Run resource is missing exact metadata.name")
        by_name[name] = item
    selected = []
    for name in names:
        if name not in baseline and resource_image(by_name[name]) == image:
            selected.append(name)
    return tuple(selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--discover-name")
    group.add_argument("--resource-image", action="store_true")
    group.add_argument("--job-config", action="store_true")
    group.add_argument("--job-replace-manifest", action="store_true")
    group.add_argument("--revision-names", action="store_true")
    group.add_argument("--new-image-revisions")
    parser.add_argument("--baseline-file", type=Path)
    args = parser.parse_args()

    try:
        resource = json.load(sys.stdin)
        values: tuple[str, ...]
        if args.discover_name:
            values = (discover_resource(resource, args.discover_name),)
        elif args.resource_image:
            values = (resource_image(resource),)
        elif args.job_config:
            values = (json.dumps(job_config(resource), sort_keys=True, separators=(",", ":")),)
        elif args.job_replace_manifest:
            values = (
                json.dumps(job_replace_manifest(resource), sort_keys=True, separators=(",", ":")),
            )
        elif args.revision_names:
            values = revision_names(resource)
        else:
            if args.baseline_file is None:
                parser.error("--new-image-revisions requires --baseline-file")
            baseline = {
                line.strip()
                for line in args.baseline_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
            values = new_image_revisions(
                resource,
                image=args.new_image_revisions,
                baseline=baseline,
            )
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    for value in values:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
