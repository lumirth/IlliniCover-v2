#!/usr/bin/env python3
"""Validate semantic invariants owned by repository operations configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SHA_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


class OpsConfigurationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OpsConfigurationError(message)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path}: expected a YAML object")
    return value


def containers(resource: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            candidate = value.get("containers")
            if isinstance(candidate, list):
                result.extend(item for item in candidate if isinstance(item, dict))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(resource)
    return result


def environment(resource: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for container in containers(resource):
        for item in container.get("env", []):
            if isinstance(item, dict) and isinstance(item.get("value"), str):
                result[item.get("name", "")] = item["value"]
    return result


def validate_workflows() -> None:
    workflow_directory = ROOT / ".github/workflows"
    required = {"ci.yml", "deploy.yml", "preview.yml", "model-evaluation.yml"}
    actual = {path.name for path in workflow_directory.glob("*.yml")}
    require(required <= actual, f"missing workflows: {sorted(required - actual)}")
    for path in workflow_directory.glob("*.yml"):
        workflow = load_yaml(path)
        require("concurrency" in workflow, f"{path}: concurrency is required")
        for job in workflow.get("jobs", {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps", []):
                if isinstance(step, dict) and isinstance(step.get("uses"), str):
                    require(SHA_ACTION.match(step["uses"]) is not None, f"{path}: unpinned action")

    ci = load_yaml(workflow_directory / "ci.yml")
    require(ci["jobs"]["required"]["name"] == "CI / Required", "CI required name drift")
    ci_source = (workflow_directory / "ci.yml").read_text(encoding="utf-8")
    require(
        ci_source.count("--diff-filter=ACDMRT") >= 2,
        "CI path and migration classification must include deleted files",
    )
    require(
        'MIGRATION_BASE_SHA: ${{ github.event.pull_request.base.sha }}' in ci_source
        and '--base "$MIGRATION_BASE_SHA"' in ci_source,
        "PR migration classification must bind the exact base commit",
    )
    migration_fresh = ci["jobs"]["migration-fresh"]
    require(
        migration_fresh.get("needs") == "classify"
        and migration_fresh.get("if") == "needs.classify.outputs.migrations == 'true'"
        and "migration-fresh" in ci["jobs"]["required"].get("needs", []),
        "every migration change, including the initial source import, must require "
        "fresh PostgreSQL",
    )
    postgres = ci["jobs"]["backend"]["services"]["postgres"]["image"]
    require("postgres:18.4" in postgres and "@sha256:" in postgres, "CI PostgreSQL must be pinned")
    deploy = load_yaml(workflow_directory / "deploy.yml")
    require(
        deploy["jobs"]["deploy"]["permissions"].get("id-token") == "write",
        "deploy WIF permission missing",
    )
    require(
        "id-token" not in deploy["jobs"]["classify"].get("permissions", {})
        and "id-token" not in deploy["permissions"],
        "provider-free classifier must not receive OIDC authority",
    )
    require(
        deploy["jobs"]["deploy"].get("environment") == "production",
        "production environment gate missing",
    )
    require(
        deploy["jobs"]["deploy"].get("needs") == "classify"
        and deploy["jobs"]["deploy"].get("if")
        == "needs.classify.outputs.deploy == 'true'",
        "provider deployment must be gated by runtime-path classification",
    )
    deploy_source = (workflow_directory / "deploy.yml").read_text(encoding="utf-8")
    classifier_position = deploy_source.find("classify_runtime_changes.py")
    auth_position = deploy_source.find("google-github-actions/auth@")
    require(
        classifier_position >= 0 and auth_position > classifier_position,
        "runtime classification must run before GCP authentication",
    )
    require(
        "Record non-runtime no-op" in deploy_source
        and "no provider step ran" in deploy_source,
        "non-runtime main advances must record a provider-free no-op",
    )
    require(
        "Re-evaluate exceptional migrations before any provider mutation" in deploy_source
        and "migration_evidence.py release" in deploy_source
        and '--base "$BEFORE_SHA"' in deploy_source,
        "production deploy must independently verify exceptional migration receipts",
    )
    require(
        "Bound billable Secret Manager inventory before a build" in deploy_source
        and deploy_source.find("secret_version_guard.py check")
        < deploy_source.find("gcloud builds submit"),
        "production Secret Manager inventory must be bounded before Cloud Build",
    )
    require(
        deploy_source.count("GCP_OTHER_PROJECT_ACTIVE_SECRET_VERSIONS") >= 3,
        "production billing-account secret inventory receipt is required",
    )
    require(
        'NEW_IMAGE_RESERVE_BYTES: "268435456"' in deploy_source
        and "256 MiB headroom" in deploy_source
        and "167772160" not in deploy_source
        and "160 MiB" not in deploy_source,
        "production build preflight must reserve the observed-safe 256 MiB envelope",
    )
    require(
        deploy_source.count("artifact_image_cleanup.py") >= 1
        and "RELEASE_IMAGE_BUILT: ${{ steps.image.outputs.built }}" in deploy_source
        and "gcloud artifacts docker images delete" not in deploy_source,
        "production artifact rejection and release failure must use verified OCI cleanup",
    )
    preview = load_yaml(workflow_directory / "preview.yml")
    require(
        preview["concurrency"]["group"] == "shared-preview",
        "preview concurrency must be global",
    )
    require(not preview["concurrency"]["cancel-in-progress"], "preview mutations must serialize")
    preview_source = (workflow_directory / "preview.yml").read_text(encoding="utf-8")
    require(
        preview_source.count('--expected-env "DEPLOYMENT_ENVIRONMENT=preview"') >= 3,
        "preview jobs and service must read back the exact deployment environment",
    )
    require(
        "Bound billable Secret Manager rotation before provider data changes" in preview_source
        and "Retire only superseded preview versions after accepted readback" in preview_source,
        "preview secret candidates require bounded preflight and post-acceptance retirement",
    )
    require(
        preview_source.count("GCP_OTHER_PROJECT_ACTIVE_SECRET_VERSIONS") >= 2,
        "preview billing-account secret inventory receipt is required",
    )
    require(
        "GCP_PREVIEW_WORKLOAD_IDENTITY_PROVIDER" in preview_source
        and "GCP_WORKLOAD_IDENTITY_PROVIDER" not in preview_source,
        "preview must use its distinct WIF provider variable",
    )
    require(
        "illinicover-preview-web:latest" not in preview_source
        and "illinicover-preview-migrate:latest" not in preview_source,
        "preview Cloud Run resources must pin numeric Secret Manager versions",
    )
    require(
        'NEW_IMAGE_RESERVE_BYTES: "268435456"' in preview_source
        and "before > ARTIFACT_FREE_BYTES - NEW_IMAGE_RESERVE_BYTES" in preview_source
        and "256 MiB preview-build headroom" in preview_source
        and "332227840" not in preview_source
        and "160 MiB" not in preview_source,
        "preview build preflight must reserve the observed-safe 256 MiB envelope",
    )
    require(
        "artifact_image_cleanup.py" in preview_source
        and "gcloud artifacts docker images delete" not in preview_source,
        "rejected preview image cleanup must verify its full OCI closure",
    )


def validate_cloud_run() -> None:
    resources = {path.name: load_yaml(path) for path in (ROOT / "ops/cloudrun").glob("*.yaml")}
    expected = {
        "prod-service.yaml",
        "preview-service.yaml",
        "migrate-job.yaml",
        "bootstrap-job.yaml",
        "refresh-job.yaml",
        "nightly-job.yaml",
    }
    require(expected == set(resources), "Cloud Run recurring manifest set drifted")
    prod = resources["prod-service.yaml"]
    preview = resources["preview-service.yaml"]
    require(
        prod["spec"]["template"]["metadata"]["annotations"]["autoscaling.knative.dev/maxScale"]
        == "3",
        "production max scale must be 3",
    )
    require(
        preview["spec"]["template"]["metadata"]["annotations"]["autoscaling.knative.dev/maxScale"]
        == "1",
        "preview max scale must be 1",
    )
    require(
        "illinicover-web@" in prod["spec"]["template"]["spec"]["serviceAccountName"],
        "web service account drift",
    )
    require(
        "illinicover-preview-web@"
        in preview["spec"]["template"]["spec"]["serviceAccountName"],
        "preview service account drift",
    )

    expected_modes = {
        "prod-service.yaml": "pooled",
        "preview-service.yaml": "pooled",
        "migrate-job.yaml": "direct",
        "bootstrap-job.yaml": "pooled",
        "refresh-job.yaml": "pooled",
        "nightly-job.yaml": "pooled",
    }
    expected_environments = {
        "prod-service.yaml": "production",
        "preview-service.yaml": "preview",
        "migrate-job.yaml": "production",
        "bootstrap-job.yaml": "production",
        "refresh-job.yaml": "production",
        "nightly-job.yaml": "production",
    }
    for name, mode in expected_modes.items():
        resource = resources[name]
        require(environment(resource).get("DATABASE_MODE") == mode, f"{name}: database mode drift")
        require(
            environment(resource).get("DEPLOYMENT_ENVIRONMENT") == expected_environments[name],
            f"{name}: deployment environment drift",
        )
        for container in containers(resource):
            image = container.get("image", "")
            require("@sha256:IMAGE_DIGEST_REQUIRED" in image, f"{name}: image is not digest-shaped")
        if resource.get("kind") == "Job":
            task = resource["spec"]["template"]["spec"]["template"]["spec"]
            timeout = int(task["timeoutSeconds"])
            require(timeout <= 3600, f"{name}: task timeout must stay at or below 3600 seconds")
        secret_versions = [
            item.get("valueFrom", {}).get("secretKeyRef", {}).get("key")
            for container in containers(resource)
            for item in container.get("env", [])
            if isinstance(item, dict) and item.get("name") == "ILLINICOVER_SECRETS_JSON"
        ]
        require(
            secret_versions == ["SECRET_VERSION_REQUIRED"],
            f"{name}: Secret Manager version must be an exact-version placeholder",
        )

    for name in ("prod-service.yaml", "preview-service.yaml"):
        probes = resources[name]["spec"]["template"]["spec"]["containers"][0]
        require(
            probes["readinessProbe"]["httpGet"]["path"] == "/health/live",
            f"{name}: recurring readiness must remain process-only",
        )


def validate_artifact_policy() -> None:
    policy = json.loads(
        (ROOT / "ops/deployment/artifact-cleanup-policy.json").read_text(encoding="utf-8")
    )
    keep_prefixes: set[str] = set()
    for rule in policy:
        if rule.get("action", {}).get("type") == "Keep":
            keep_prefixes.update(rule.get("condition", {}).get("tagPrefixes", []))
    require(
        {"production-serving", "production-rollback", "preview-serving"} <= keep_prefixes,
        "cleanup policy must preserve serving and rollback tags",
    )
    source_policy = json.loads(
        (ROOT / "ops/deployment/cloudbuild-source-lifecycle.json").read_text(
            encoding="utf-8"
        )
    )
    require(
        source_policy == {
            "rule": [
                {
                    "action": {"type": "Delete"},
                    "condition": {"age": 1},
                }
            ]
        },
        "Cloud Build source staging must expire after one day",
    )


def validate_secret_version_lifecycle() -> None:
    deploy = (ROOT / "ops/deployment/deploy-cloud-run.sh").read_text(encoding="utf-8")
    require(
        "secret_version_guard.py check" in deploy
        and "secret_version_guard.py retire" in deploy,
        "production release must bound and retire Secret Manager versions",
    )
    require(
        "${WEB_SECRET_NAME}:latest" not in deploy
        and "${MIGRATE_SECRET_NAME}:latest" not in deploy
        and "${JOBS_SECRET_NAME}:latest" not in deploy,
        "production Cloud Run resources must pin numeric Secret Manager versions",
    )
    require(
        deploy.rfind("trap - EXIT HUP INT TERM")
        < deploy.find("secret_version_guard.py retire"),
        "secret retirement must happen only after the accepted-release trap is disarmed",
    )
    require(
        "NEW_IMAGE_RESERVE_BYTES=268435456" in deploy
        and "256 MiB headroom" in deploy
        and "167772160" not in deploy
        and "160 MiB" not in deploy,
        "manual release build preflight must reserve the observed-safe 256 MiB envelope",
    )
    require(
        "scripts/release/artifact_image_cleanup.py" in deploy
        and 'RELEASE_IMAGE_BUILT="${RELEASE_IMAGE_BUILT:-false}"' in deploy
        and "gcloud artifacts docker images delete" not in deploy,
        "manual and workflow release failures must use verified OCI cleanup",
    )
    deployment_runbook = (ROOT / "docs/runbooks/deployment.md").read_text(
        encoding="utf-8"
    )
    require(
        "requires 256 MiB" in deployment_runbook
        and "billed-size counter may lag" in deployment_runbook
        and "160 MiB" not in deployment_runbook,
        "deployment runbook must document the observed-safe reserve and asynchronous cleanup",
    )


def main() -> int:
    validate_workflows()
    validate_cloud_run()
    validate_artifact_policy()
    validate_secret_version_lifecycle()
    print("operations configuration invariants passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
