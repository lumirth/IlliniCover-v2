import os
import subprocess
from pathlib import Path

REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64
IMAGE = f"us-east5-docker.pkg.dev/illinicover/releases/backend@{DIGEST}"
SCHEDULER_URI = "https://run.googleapis.com/v2/projects/illinicover/locations/us-east5/jobs/illinicover-reconcile:run"
SCHEDULER_IDENTITY = "illinicover-scheduler@illinicover.iam.gserviceaccount.com"


def executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(0o755)


def test_first_deploy_prepares_and_probes_before_traffic(tmp_path: Path) -> None:
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls"
    state = tmp_path / "state"
    public = tmp_path / "public"
    legacy_scheduler = tmp_path / "legacy-scheduler"
    legacy_bootstrap = tmp_path / "legacy-bootstrap"
    legacy_nightly = tmp_path / "legacy-nightly"
    legacy_refresh = tmp_path / "legacy-refresh"
    broad_invoker = tmp_path / "broad-invoker"
    for resource in (
        legacy_scheduler,
        legacy_bootstrap,
        legacy_nightly,
        legacy_refresh,
        broad_invoker,
    ):
        resource.write_text("present")
    executable(
        binary / "gcloud",
        """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
log, state = Path(os.environ["FAKE_LOG"]), Path(os.environ["FAKE_STATE"])
with log.open("a") as output:
    output.write("gcloud " + " ".join(args) + "\\n")
image, revision = os.environ["IMAGE"], os.environ["CODE_REVISION"]
candidate = "illinicover-api-sha-aaaaaaaaaa-42-1"
previous = "illinicover-api-old"
scheduler = state.with_name("scheduler")
public = state.with_name("public")
legacy_scheduler = state.with_name("legacy-scheduler")
legacy_bootstrap = state.with_name("legacy-bootstrap")
legacy_nightly = state.with_name("legacy-nightly")
legacy_refresh = state.with_name("legacy-refresh")
broad_invoker = state.with_name("broad-invoker")
broad_public = state.with_name("broad-public")
scheduler_uri = "https://run.googleapis.com/v2/projects/illinicover/locations/us-east5/jobs/illinicover-reconcile:run"
scheduler_identity = "illinicover-scheduler@illinicover.iam.gserviceaccount.com"

def resource(mode, secret):
    return {"spec": {"containers": [{
        "image": image,
        "env": [
            {"name": "CODE_REVISION", "value": revision},
            {"name": "DATABASE_MODE", "value": mode},
            {"name": "DEPLOYMENT_ENVIRONMENT", "value": "production"},
            {"name": "ILLINICOVER_SECRETS_JSON", "valueFrom": {
                "secretKeyRef": {"name": secret, "key": "7"}
            }},
        ],
    }]}}

if args[:3] == ["secrets", "versions", "describe"]:
    print("projects/p/secrets/s/versions/7 ENABLED")
elif args[:3] == ["run", "jobs", "list"]:
    resources = {
        "illinicover-bootstrap": legacy_bootstrap,
        "illinicover-nightly": legacy_nightly,
        "illinicover-refresh": legacy_refresh,
    }
    for name, marker in resources.items():
        selected = any(name in value for value in args if value.startswith("--filter="))
        if marker.exists() and selected:
            print(name)
elif args[:3] == ["run", "jobs", "describe"] and args[3] in {
    "illinicover-bootstrap", "illinicover-nightly", "illinicover-refresh",
}:
    marker = {
        "illinicover-bootstrap": legacy_bootstrap,
        "illinicover-nightly": legacy_nightly,
        "illinicover-refresh": legacy_refresh,
    }[args[3]]
    if not marker.exists():
        raise SystemExit(1)
    print("{}")
elif args[:3] == ["run", "jobs", "delete"]:
    {
        "illinicover-bootstrap": legacy_bootstrap,
        "illinicover-nightly": legacy_nightly,
        "illinicover-refresh": legacy_refresh,
    }[args[3]].unlink(missing_ok=True)
elif args[:3] == ["run", "jobs", "describe"]:
    mode = "direct" if "illinicover-migrate" in args else "pooled"
    secret = "illinicover-migrate" if mode == "direct" else "illinicover-web"
    print(json.dumps(resource(mode, secret)))
elif args[:3] == ["run", "jobs", "get-iam-policy"]:
    print(json.dumps({"bindings": [{
        "role": "roles/run.invoker",
        "members": ["serviceAccount:" + scheduler_identity],
    }]}))
elif args[:3] == ["run", "revisions", "list"]:
    if state.exists() and state.read_text() not in {"existing"}:
        print(candidate)
elif args[:3] == ["run", "revisions", "describe"]:
    if not state.exists() or state.read_text() not in {
        "deployed_first", "promoted_first", "deployed_existing",
        "promoted_existing", "promoted_first_clean", "promoted_existing_clean",
        "restored_tagged", "restored_clean",
    }:
        raise SystemExit(1)
    print(json.dumps(resource("pooled", "illinicover-web")))
elif args[:3] == ["run", "revisions", "delete"]:
    if state.exists() and state.read_text() == "restored_clean":
        state.write_text("existing")
elif args[:3] == ["run", "services", "list"]:
    if os.environ.get("FAIL_SERVICE_LIST"):
        raise SystemExit(1)
    if state.exists():
        print("illinicover-api")
elif args[:3] == ["run", "services", "describe"]:
    if not state.exists():
        raise SystemExit(1)
    mode = state.read_text()
    traffic = []
    if mode in {"existing", "deployed_existing", "restored_tagged", "restored_clean"}:
        traffic.append({"revisionName": previous, "percent": 100})
    if mode == "deployed_first":
        traffic.append({
            "revisionName": candidate, "tag": "candidate",
            "url": "https://candidate.test", "percent": 100,
        })
    if mode in {"deployed_existing", "restored_tagged"}:
        traffic.append({"revisionName": candidate, "tag": "candidate", "url": "https://candidate.test"})
    if mode in {"promoted_first", "promoted_existing"}:
        traffic.append({
            "revisionName": candidate, "tag": "candidate",
            "url": "https://candidate.test", "percent": 100,
        })
    if mode in {"promoted_first_clean", "promoted_existing_clean"}:
        traffic.append({"revisionName": candidate, "percent": 100})
    if any("value(status.url)" in value for value in args):
        print("https://service.test")
    else:
        print(json.dumps({"status": {"traffic": traffic, "url": "https://service.test"}}))
elif args[:2] == ["run", "deploy"]:
    if not state.exists() and "--no-traffic" in args:
        raise SystemExit("--no-traffic not supported when creating a new service")
    state.write_text("deployed_existing" if state.exists() else "deployed_first")
elif args[:3] == ["run", "services", "update-traffic"]:
    mode = state.read_text()
    if "--remove-tags" in args:
        clean = {
            "deployed_first": "promoted_first_clean",
            "promoted_first": "promoted_first_clean",
            "promoted_existing": "promoted_existing_clean",
            "restored_tagged": "restored_clean",
        }
        state.write_text(clean.get(mode, "restored_clean"))
    elif previous + "=100" in args:
        state.write_text("restored_tagged")
    else:
        state.write_text("promoted_existing" if "existing" in mode else "promoted_first")
elif args[:3] == ["run", "services", "get-iam-policy"]:
    members = ["allUsers"] if public.exists() else []
    print(json.dumps({"bindings": [{"role": "roles/run.invoker", "members": members}]}))
elif args[:3] == ["run", "services", "add-iam-policy-binding"]:
    public.write_text("true")
elif args[:3] == ["run", "services", "delete"]:
    state.unlink(missing_ok=True)
    public.unlink(missing_ok=True)
elif args[:2] == ["auth", "print-identity-token"]:
    print("private-candidate-token")
elif args[:2] == ["projects", "remove-iam-policy-binding"]:
    broad_invoker.unlink(missing_ok=True)
elif args[:2] == ["projects", "get-iam-policy"]:
    members = ["serviceAccount:" + scheduler_identity] if broad_invoker.exists() else []
    if broad_public.exists():
        members.append("allUsers")
    print(json.dumps({"bindings": [{"role": "roles/run.invoker", "members": members}]}))
elif args[:3] == ["scheduler", "jobs", "list"]:
    if legacy_scheduler.exists():
        print("projects/p/locations/us-east4/jobs/illinicover-nightly")
    if scheduler.exists():
        print("projects/p/locations/us-east4/jobs/illinicover-reconcile")
elif args[:3] == ["scheduler", "jobs", "describe"]:
    if args[3] == "illinicover-nightly":
        if not legacy_scheduler.exists():
            raise SystemExit(1)
        print("{}")
        raise SystemExit(0)
    if not scheduler.exists():
        raise SystemExit(1)
    print(json.dumps({
        "httpTarget": {"uri": scheduler_uri, "oauthToken": {
            "serviceAccountEmail": scheduler_identity,
        }},
        "schedule": "17 10 * * *", "timeZone": "Etc/UTC", "state": "ENABLED",
    }))
elif args[:4] == ["scheduler", "jobs", "create", "http"]:
    scheduler.write_text("created")
elif args[:3] == ["scheduler", "jobs", "delete"]:
    legacy_scheduler.unlink(missing_ok=True)
""",
    )
    executable(
        binary / "curl",
        """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

url = sys.argv[-1]
with Path(os.environ["FAKE_LOG"]).open("a") as output:
    output.write("curl " + url + "\\n")
if os.environ.get("FAIL_STABLE_PROBE") and url.startswith("https://api.test"):
    raise SystemExit(22)
if os.environ.get("FAIL_CANDIDATE_PROBE") and url.startswith("https://candidate.test"):
    raise SystemExit(22)
if url.endswith("/api/cover"):
    print(json.dumps({"venues": [{"cover": {"price": {"kind": "single"}}}]}))
elif url.endswith("/api/deals"):
    print(json.dumps({"venues": [{"deals": [{"id": "deal"}]}]}))
else:
    print(json.dumps({"status": "ready" if url.endswith("/health/ready") else "ok"}))
""",
    )
    environment = os.environ | {
        "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
        "FAKE_LOG": str(log),
        "FAKE_STATE": str(state),
        "GCP_PROJECT_ID": "illinicover",
        "GCP_REGION": "us-east5",
        "ARTIFACT_REPOSITORY": "releases",
        "PUBLIC_API_ORIGIN": "https://api.test",
        "CODE_REVISION": REVISION,
        "IMAGE": IMAGE,
        "GITHUB_RUN_ID": "42",
        "PREALPHA_CUTOVER": "true",
    }
    result = subprocess.run(
        ["bash", "ops/deployment/deploy-cloud-run.sh"],
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert "bootstrap --settings=config.settings.production" in calls
    deploy = calls.index("gcloud run deploy")
    candidate_probe = calls.index("curl https://candidate.test/health/live")
    promote = calls.index("gcloud run services add-iam-policy-binding")
    stable_probe = calls.index("curl https://api.test/health/live")
    reconcile = calls.index("gcloud run jobs deploy illinicover-reconcile")
    invoker = calls.index("gcloud run jobs add-iam-policy-binding illinicover-reconcile")
    scheduler_create = calls.index("gcloud scheduler jobs create http illinicover-reconcile")
    assert (
        deploy < candidate_probe < promote < stable_probe < reconcile < invoker < scheduler_create
    )
    deploy_call = calls[deploy : calls.index("\n", deploy)]
    assert "--no-traffic" not in deploy_call and "--allow-unauthenticated" not in deploy_call
    assert "gcloud auth print-identity-token --audiences=https://service.test" in calls
    cutover_check = (
        "python server/manage.py verify_deploy_database "
        "--settings=config.settings.production --allow-empty"
    )
    assert cutover_check in calls
    assert "gcloud scheduler jobs delete illinicover-nightly" in calls
    assert "gcloud run jobs delete illinicover-bootstrap" in calls
    assert "gcloud run jobs delete illinicover-nightly" in calls
    assert "gcloud run jobs delete illinicover-refresh" in calls
    assert "gcloud projects remove-iam-policy-binding illinicover" in calls
    assert "reconcile_revenuecat" in calls[reconcile : calls.index("\n", reconcile)]
    assert "--command python --args server/manage.py,reconcile_revenuecat" in calls
    assert "uv run" not in calls
    assert SCHEDULER_IDENTITY in calls[invoker : calls.index("\n", invoker)]
    scheduler_call = calls[scheduler_create : calls.index("\n", scheduler_create)]
    assert SCHEDULER_URI in scheduler_call and SCHEDULER_IDENTITY in scheduler_call
    assert "TRUSTED_XFF_PROXY_HOPS=1" in deploy_call
    assert "curl https://candidate.test/api/cover" in calls
    assert "curl https://candidate.test/api/deals" in calls
    remove_tag = calls.index("--remove-tags candidate")
    assert stable_probe < remove_tag < reconcile
    assert state.read_text() == "promoted_first_clean"

    state.unlink()
    public.unlink(missing_ok=True)
    log.write_text("")
    candidate_failed = subprocess.run(
        ["bash", "ops/deployment/deploy-cloud-run.sh"],
        cwd=Path(__file__).parents[2],
        env=environment | {"FAIL_CANDIDATE_PROBE": "1"},
        capture_output=True,
        text=True,
    )
    assert candidate_failed.returncode != 0
    assert "gcloud run services delete illinicover-api" in log.read_text()
    assert not state.exists()

    state.write_text("existing")
    log.write_text("")
    existing_failed = subprocess.run(
        ["bash", "ops/deployment/deploy-cloud-run.sh"],
        cwd=Path(__file__).parents[2],
        env=environment | {"FAIL_CANDIDATE_PROBE": "1", "PREALPHA_CUTOVER": "false"},
        capture_output=True,
        text=True,
    )
    assert existing_failed.returncode != 0, existing_failed.stderr
    cleanup = log.read_text()
    existing_deploy = cleanup.index("gcloud run deploy")
    existing_deploy_call = cleanup[existing_deploy : cleanup.index("\n", existing_deploy)]
    assert "--no-traffic" in existing_deploy_call
    assert "--allow-unauthenticated" in existing_deploy_call
    assert cutover_check not in cleanup
    assert "--to-revisions illinicover-api-old=100" in cleanup
    assert "--remove-tags candidate" in cleanup
    assert "gcloud run revisions delete " + "illinicover-api-sha-aaaaaaaaaa-42-1" in cleanup
    assert state.read_text() == "existing"

    state.unlink()
    public.unlink(missing_ok=True)
    log.write_text("")
    failed = subprocess.run(
        ["bash", "ops/deployment/deploy-cloud-run.sh"],
        cwd=Path(__file__).parents[2],
        env=environment | {"FAIL_STABLE_PROBE": "1"},
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    assert "gcloud run services delete illinicover-api" in log.read_text()
    assert not state.exists()

    state.write_text("existing")
    log.write_text("")
    discovery_failed = subprocess.run(
        ["bash", "ops/deployment/deploy-cloud-run.sh"],
        cwd=Path(__file__).parents[2],
        env=environment | {"FAIL_SERVICE_LIST": "1", "PREALPHA_CUTOVER": "false"},
        capture_output=True,
        text=True,
    )
    assert discovery_failed.returncode != 0
    assert "gcloud run deploy" not in log.read_text()
    assert "gcloud run services delete" not in log.read_text()

    broad_public = state.with_name("broad-public")
    broad_public.write_text("present")
    log.write_text("")
    inherited_public = subprocess.run(
        ["bash", "ops/deployment/deploy-cloud-run.sh"],
        cwd=Path(__file__).parents[2],
        env=environment | {"PREALPHA_CUTOVER": "false"},
        capture_output=True,
        text=True,
    )
    assert inherited_public.returncode != 0
    assert "gcloud run deploy" not in log.read_text()
