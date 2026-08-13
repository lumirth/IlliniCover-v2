#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$REPOSITORY_ROOT"

GCP_PROJECT_ID="${GCP_PROJECT_ID:-illinicover}"
GCP_REGION="${GCP_REGION:-us-east5}"
REPOSITORY="${ARTIFACT_REPOSITORY:-illinicover}"
SERVICE_NAME="${CLOUD_RUN_SERVICE:-illinicover-api}"
WEB_SECRET_NAME="${WEB_SECRET_NAME:-illinicover-web}"
MIGRATE_SECRET_NAME="${MIGRATE_SECRET_NAME:-illinicover-migrate}"
JOBS_SECRET_NAME="${JOBS_SECRET_NAME:-illinicover-jobs}"
SCHEDULER_REGION="${SCHEDULER_REGION:-us-east4}"
SCHEDULER_JOB_NAME="illinicover-nightly"
SCHEDULER_SCHEDULE='17 10 * * *'
SCHEDULER_TIME_ZONE='America/Chicago'
# Cloud Scheduler cannot create a job directly in PAUSED state. This valid but
# impossible calendar schedule makes the create-then-pause transition inert.
SCHEDULER_INERT_CREATE_SCHEDULE='0 0 31 2 *'
SCHEDULER_ACCOUNT="illinicover-scheduler@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_MEMBER="serviceAccount:${SCHEDULER_ACCOUNT}"
SCHEDULER_URI="https://run.googleapis.com/v2/projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/jobs/${SCHEDULER_JOB_NAME}:run"
SCHEDULER_RESUME_MARKER="illinicover-release-guard:resume"
SCHEDULER_STABLE_DESCRIPTION="IlliniCover bounded nightly maintenance"
SCHEDULER_RELEASE_GUARD_ACTIVE=false
SCHEDULER_RESUME_AFTER_RELEASE=false
SCHEDULER_PREVIOUS_DESCRIPTION=""
SCHEDULER_RELEASE_DESCRIPTION="$SCHEDULER_STABLE_DESCRIPTION"
PUBLIC_API_ORIGIN="${PUBLIC_API_ORIGIN:-}"
RELEASE_COMMIT_SHA="${RELEASE_COMMIT_SHA:-}"
RELEASE_IMAGE_DIGEST="${RELEASE_IMAGE_DIGEST:-}"
RELEASE_IMAGE_BUILT="${RELEASE_IMAGE_BUILT:-false}"
RUN_BOOTSTRAP_ON_RELEASE="${RUN_BOOTSTRAP_ON_RELEASE:-false}"
BILLING_ACCOUNT_OTHER_ACTIVE_SECRET_VERSIONS="${BILLING_ACCOUNT_OTHER_ACTIVE_SECRET_VERSIONS:-}"
SOURCE_REVISION=""
if [[ -n "$RELEASE_COMMIT_SHA" ]]; then
  CODE_REVISION="${CODE_REVISION:-$RELEASE_COMMIT_SHA}"
else
  SOURCE_REVISION="$(python3 scripts/release/source_revision.py)"
  CODE_REVISION="${CODE_REVISION:-$SOURCE_REVISION}"
fi
IMAGE_TAG="${IMAGE_TAG:-$CODE_REVISION}"
IMAGE_REPOSITORY="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${REPOSITORY}/backend"
IMAGE_TAG_REFERENCE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
ARTIFACT_BUDGET_BYTES=1000000000
NEW_IMAGE_RESERVE_BYTES=268435456
IMAGE_BUILT_THIS_RELEASE="$RELEASE_IMAGE_BUILT"
IMAGE=""
WEB_SECRET_VERSION=""
MIGRATE_SECRET_VERSION=""
JOBS_SECRET_VERSION=""
PREVIOUS_SERVING_REVISION=""
RELEASE_TRAFFIC_SWITCHED=false
SERVICE_PUBLIC_ACCESS_PENDING=false
RELEASE_FAILURE_CLEANUP_ARMED=false
RELEASE_RESOURCE_SNAPSHOTS_READY=false
SERVICE_MUTATION_STARTED=false
RELEASE_STATE_DIRECTORY=""
RELEASE_STATE_BASE=""
RELEASE_JOB_NAMES=(
  illinicover-migrate
  illinicover-bootstrap
  illinicover-refresh
  illinicover-nightly
)

delete_unserved_release_build() {
  local image="$1"
  local digest="${image#"${IMAGE_REPOSITORY}@"}"
  if [[ "$IMAGE_BUILT_THIS_RELEASE" != "true" ]]; then
    return 0
  fi
  if [[ "$image" != "${IMAGE_REPOSITORY}@${digest}" \
    || ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "CRITICAL: refusing cleanup without the exact newly built image digest." >&2
    return 1
  fi
  python3 scripts/release/artifact_image_cleanup.py \
    --project "$GCP_PROJECT_ID" \
    --location "$GCP_REGION" \
    --repository "$REPOSITORY" \
    --package backend \
    --digest "$digest" \
    --execute
  IMAGE_BUILT_THIS_RELEASE=false
  echo "Removed and verified the exact newly built, unserved release image ${image}." >&2
}

cloud_run_job_state() {
  local job="$1"
  gcloud run jobs list \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --format=json \
  | python3 scripts/release/cloud_run_release_state.py --discover-name "$job"
}

snapshot_release_resources() {
  local jobs_json
  local job
  local state

  RELEASE_STATE_BASE="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
  if [[ ! -d "$RELEASE_STATE_BASE" || -L "$RELEASE_STATE_BASE" ]]; then
    echo "CRITICAL: release state base is not a real directory." >&2
    return 1
  fi
  RELEASE_STATE_DIRECTORY="$(mktemp -d "${RELEASE_STATE_BASE%/}/illinicover-release.XXXXXX")"
  if [[ ! -d "$RELEASE_STATE_DIRECTORY" || -L "$RELEASE_STATE_DIRECTORY" \
    || "$RELEASE_STATE_DIRECTORY" != "${RELEASE_STATE_BASE%/}/illinicover-release."* ]]; then
    echo "CRITICAL: unable to create a bounded release state directory." >&2
    return 1
  fi

  jobs_json="$(gcloud run jobs list \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --format=json)"
  for job in "${RELEASE_JOB_NAMES[@]}"; do
    state="$(python3 scripts/release/cloud_run_release_state.py \
      --discover-name "$job" <<<"$jobs_json")"
    printf '%s\n' "$state" > "${RELEASE_STATE_DIRECTORY}/${job}.state"
    if [[ "$state" == "PRESENT" ]]; then
      gcloud run jobs describe "$job" \
        --project "$GCP_PROJECT_ID" \
        --region "$GCP_REGION" \
        --format=json > "${RELEASE_STATE_DIRECTORY}/${job}.json"
      python3 scripts/release/cloud_run_release_state.py --job-config \
        < "${RELEASE_STATE_DIRECTORY}/${job}.json" \
        > "${RELEASE_STATE_DIRECTORY}/${job}.config"
      python3 scripts/release/cloud_run_release_state.py --job-replace-manifest \
        < "${RELEASE_STATE_DIRECTORY}/${job}.json" \
        > "${RELEASE_STATE_DIRECTORY}/${job}.restore.json"
    elif [[ "$state" != "ABSENT" ]]; then
      echo "CRITICAL: unexpected Cloud Run job state ${state} for ${job}." >&2
      return 1
    fi
  done

  if [[ "${SERVICE_PREVIOUS_STATE:-}" == "PRESENT" ]]; then
    gcloud run revisions list \
      --service "$SERVICE_NAME" \
      --project "$GCP_PROJECT_ID" \
      --region "$GCP_REGION" \
      --format=json \
    | python3 scripts/release/cloud_run_release_state.py --revision-names \
      > "${RELEASE_STATE_DIRECTORY}/service-revisions.before"
  else
    : > "${RELEASE_STATE_DIRECTORY}/service-revisions.before"
  fi
  RELEASE_RESOURCE_SNAPSHOTS_READY=true
}

mark_release_job_mutation() {
  local job="$1"
  : > "${RELEASE_STATE_DIRECTORY}/${job}.mutated"
}

restore_release_job() {
  local job="$1"
  local current_config
  local current_state
  local state

  if [[ ! -f "${RELEASE_STATE_DIRECTORY}/${job}.mutated" ]]; then
    return 0
  fi
  state="$(<"${RELEASE_STATE_DIRECTORY}/${job}.state")"
  if [[ "$state" == "PRESENT" ]]; then
    if ! gcloud run jobs replace "${RELEASE_STATE_DIRECTORY}/${job}.restore.json" \
      --project "$GCP_PROJECT_ID" \
      --region "$GCP_REGION" \
      --quiet; then
      echo "CRITICAL: unable to restore ${job}." >&2
      return 1
    fi
    if ! current_config="$(gcloud run jobs describe "$job" \
      --project "$GCP_PROJECT_ID" \
      --region "$GCP_REGION" \
      --format=json \
      | python3 scripts/release/cloud_run_release_state.py --job-config)"; then
      echo "CRITICAL: unable to read back restored job ${job}." >&2
      return 1
    fi
    if [[ "$current_config" != "$(<"${RELEASE_STATE_DIRECTORY}/${job}.config")" ]]; then
      echo "CRITICAL: ${job} did not restore its complete pre-release configuration." >&2
      return 1
    fi
  elif [[ "$state" == "ABSENT" ]]; then
    if ! current_state="$(cloud_run_job_state "$job")"; then
      echo "CRITICAL: unable to discover newly created job ${job}." >&2
      return 1
    fi
    if [[ "$current_state" == "PRESENT" ]]; then
      if ! gcloud run jobs delete "$job" \
        --project "$GCP_PROJECT_ID" \
        --region "$GCP_REGION" \
        --quiet; then
        echo "CRITICAL: unable to delete newly created job ${job}." >&2
        return 1
      fi
    fi
    if ! current_state="$(cloud_run_job_state "$job")"; then
      echo "CRITICAL: unable to verify deletion of ${job}." >&2
      return 1
    fi
    if [[ "$current_state" != "ABSENT" ]]; then
      echo "CRITICAL: newly created ${job} remains after release rollback." >&2
      return 1
    fi
  else
    echo "CRITICAL: invalid saved Cloud Run job state for ${job}." >&2
    return 1
  fi
}

restore_release_service() {
  local revision
  local revisions
  local service_state

  if [[ "$SERVICE_MUTATION_STARTED" != "true" ]]; then
    return 0
  fi
  if ! service_state="$(gcloud run services list \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --format=json \
    | python3 scripts/release/service_release.py --discover-name "$SERVICE_NAME")"; then
    echo "CRITICAL: unable to discover ${SERVICE_NAME} during rollback." >&2
    return 1
  fi
  if [[ "${SERVICE_PREVIOUS_STATE:-}" == "ABSENT" ]]; then
    if [[ "$service_state" == "PRESENT" ]]; then
      if ! gcloud run services delete "$SERVICE_NAME" \
        --project "$GCP_PROJECT_ID" \
        --region "$GCP_REGION" \
        --quiet; then
        echo "CRITICAL: unable to delete newly created ${SERVICE_NAME}." >&2
        return 1
      fi
    fi
    if ! service_state="$(gcloud run services list \
      --project "$GCP_PROJECT_ID" \
      --region "$GCP_REGION" \
      --format=json \
      | python3 scripts/release/service_release.py --discover-name "$SERVICE_NAME")"; then
      echo "CRITICAL: unable to verify deletion of ${SERVICE_NAME}." >&2
      return 1
    fi
    if [[ "$service_state" != "ABSENT" ]]; then
      echo "CRITICAL: newly created ${SERVICE_NAME} remains after release rollback." >&2
      return 1
    fi
    return 0
  fi
  if [[ "${SERVICE_PREVIOUS_STATE:-}" != "PRESENT" || "$service_state" != "PRESENT" ]]; then
    echo "CRITICAL: existing ${SERVICE_NAME} is unavailable during release rollback." >&2
    return 1
  fi

  if ! gcloud run services update-traffic "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --remove-tags candidate \
    --quiet; then
    echo "CRITICAL: unable to remove the failed candidate traffic tag." >&2
    return 1
  fi
  if ! revisions="$(gcloud run revisions list \
    --service "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
      --format=json \
      | python3 scripts/release/cloud_run_release_state.py \
        --new-image-revisions "$IMAGE" \
        --baseline-file "${RELEASE_STATE_DIRECTORY}/service-revisions.before")"; then
    echo "CRITICAL: unable to inventory failed-release revisions." >&2
    return 1
  fi
  while IFS= read -r revision; do
    [[ -n "$revision" ]] || continue
    if ! gcloud run revisions delete "$revision" \
      --project "$GCP_PROJECT_ID" \
      --region "$GCP_REGION" \
      --quiet; then
      echo "CRITICAL: unable to delete failed-release revision ${revision}." >&2
      return 1
    fi
  done <<<"$revisions"
  if ! revisions="$(gcloud run revisions list \
    --service "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
      --format=json \
      | python3 scripts/release/cloud_run_release_state.py \
        --new-image-revisions "$IMAGE" \
        --baseline-file "${RELEASE_STATE_DIRECTORY}/service-revisions.before")"; then
    echo "CRITICAL: unable to verify failed-release revision cleanup." >&2
    return 1
  fi
  if [[ -n "$revisions" ]]; then
    echo "CRITICAL: a failed-release revision still pins ${IMAGE}." >&2
    return 1
  fi
}

restore_release_resources_on_failure() {
  local failed=0
  local job

  if [[ "$RELEASE_RESOURCE_SNAPSHOTS_READY" != "true" ]]; then
    return 0
  fi
  for job in "${RELEASE_JOB_NAMES[@]}"; do
    restore_release_job "$job" || failed=1
  done
  restore_release_service || failed=1
  return "$failed"
}

cleanup_release_state_directory() {
  local job

  if [[ -z "$RELEASE_STATE_DIRECTORY" ]]; then
    return 0
  fi
  if [[ ! -d "$RELEASE_STATE_DIRECTORY" || -L "$RELEASE_STATE_DIRECTORY" \
    || "$RELEASE_STATE_DIRECTORY" != "${RELEASE_STATE_BASE%/}/illinicover-release."* ]]; then
    echo "CRITICAL: refusing to remove an unbounded release state path." >&2
    return 1
  fi
  for job in "${RELEASE_JOB_NAMES[@]}"; do
    rm -f -- \
      "${RELEASE_STATE_DIRECTORY}/${job}.state" \
      "${RELEASE_STATE_DIRECTORY}/${job}.json" \
      "${RELEASE_STATE_DIRECTORY}/${job}.config" \
      "${RELEASE_STATE_DIRECTORY}/${job}.restore.json" \
      "${RELEASE_STATE_DIRECTORY}/${job}.mutated"
  done
  rm -f -- "${RELEASE_STATE_DIRECTORY}/service-revisions.before"
  rmdir -- "$RELEASE_STATE_DIRECTORY"
  RELEASE_STATE_DIRECTORY=""
}

scheduler_current_state() {
  gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" \
    --project "$GCP_PROJECT_ID" \
    --location "$SCHEDULER_REGION" \
    --format='value(state)'
}

scheduler_current_description() {
  gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" \
    --project "$GCP_PROJECT_ID" \
    --location "$SCHEDULER_REGION" \
    --format='value(description)'
}

scheduler_pause_on_exit() {
  local exit_status=$?
  local current_state=""

  trap - EXIT HUP INT TERM
  if [[ "${SERVICE_PUBLIC_ACCESS_PENDING:-false}" == "true" ]]; then
    set +e
    gcloud run services remove-iam-policy-binding "$SERVICE_NAME" \
      --project "$GCP_PROJECT_ID" \
      --region "$GCP_REGION" \
      --member allUsers \
      --role roles/run.invoker \
      --quiet
    if [[ -z "$(gcloud run services get-iam-policy "$SERVICE_NAME" \
      --project "$GCP_PROJECT_ID" \
      --region "$GCP_REGION" \
      --flatten='bindings[].members' \
      --filter='bindings.role=roles/run.invoker AND bindings.members=allUsers' \
      --format='value(bindings.members)')" ]]; then
      echo "First release failed; ${SERVICE_NAME} was returned to private access." >&2
    else
      echo "CRITICAL: failed first release remains publicly invokable." >&2
      exit_status=3
    fi
  fi
  if [[ "${RELEASE_TRAFFIC_SWITCHED:-false}" == "true" ]]; then
    set +e
    if [[ -n "${PREVIOUS_SERVING_REVISION:-}" ]]; then
      gcloud run services update-traffic "$SERVICE_NAME" \
        --project "$GCP_PROJECT_ID" \
        --region "$GCP_REGION" \
        --to-revisions "${PREVIOUS_SERVING_REVISION}=100" \
        --quiet
      if gcloud run services describe "$SERVICE_NAME" \
        --project "$GCP_PROJECT_ID" \
        --region "$GCP_REGION" \
        --format=json \
        | python3 scripts/release/service_release.py --serving-revision \
        | grep -Fxq "$PREVIOUS_SERVING_REVISION"; then
        echo "Release failed after traffic changed; restored ${PREVIOUS_SERVING_REVISION}." >&2
      else
        echo "CRITICAL: unable to verify rollback to ${PREVIOUS_SERVING_REVISION}." >&2
        exit_status=3
      fi
    else
      echo "CRITICAL: traffic changed without a recorded rollback revision." >&2
      exit_status=3
    fi
  fi
  if [[ "${SCHEDULER_RELEASE_GUARD_ACTIVE:-false}" == "true" ]]; then
    # A zero exit while the guard is armed means the release path forgot to
    # make an explicit final scheduling decision. Fail closed in that case.
    if (( exit_status == 0 )); then
      exit_status=3
    fi
    set +e
    current_state="$(scheduler_current_state 2>/dev/null)"
    if [[ "$current_state" != "PAUSED" ]]; then
      gcloud scheduler jobs pause "$SCHEDULER_JOB_NAME" \
        --project "$GCP_PROJECT_ID" \
        --location "$SCHEDULER_REGION" \
        --quiet
      current_state="$(scheduler_current_state 2>/dev/null)"
    fi
    if [[ "$current_state" == "PAUSED" ]]; then
      echo "Release did not complete; ${SCHEDULER_JOB_NAME} remains paused." >&2
    elif [[ "$current_state" == "" ]]; then
      echo "CRITICAL: unable to verify ${SCHEDULER_JOB_NAME} is paused." >&2
      exit_status=3
    else
      echo "CRITICAL: unable to leave ${SCHEDULER_JOB_NAME} paused (state: ${current_state})." >&2
      exit_status=3
    fi
  fi
  if [[ "${RELEASE_FAILURE_CLEANUP_ARMED:-false}" == "true" ]]; then
    if restore_release_resources_on_failure; then
      if ! delete_unserved_release_build "${IMAGE:-}"; then
        echo "CRITICAL: failed-release artifact cleanup did not complete." >&2
        exit_status=3
      fi
    else
      echo "CRITICAL: runtime references were not restored; retaining the release image." >&2
      exit_status=3
    fi
    if ! cleanup_release_state_directory; then
      exit_status=3
    fi
  fi
  exit "$exit_status"
}

if [[ "$GCP_PROJECT_ID" == "lukashermes" ]]; then
  echo "Refusing to deploy IlliniCover into the unrelated lukashermes project." >&2
  exit 2
fi
if [[ -z "$GCP_PROJECT_ID" || -z "$GCP_REGION" || -z "$IMAGE_TAG_REFERENCE" || -z "$PUBLIC_API_ORIGIN" ]]; then
  echo "Resolved deployment values must not be empty." >&2
  echo "Set PUBLIC_API_ORIGIN to the actual Cloud Run or custom HTTPS origin." >&2
  exit 2
fi
if [[ ! "$PUBLIC_API_ORIGIN" =~ ^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$ ]]; then
  echo "PUBLIC_API_ORIGIN must be a path-free HTTPS origin without a trailing slash." >&2
  exit 2
fi
if [[ -n "$RELEASE_COMMIT_SHA" && ! "$RELEASE_COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "RELEASE_COMMIT_SHA must be the exact lowercase 40-character Git commit SHA." >&2
  exit 2
fi
if [[ -n "$RELEASE_COMMIT_SHA" && "$CODE_REVISION" != "$RELEASE_COMMIT_SHA" ]]; then
  echo "CODE_REVISION must exactly match RELEASE_COMMIT_SHA in the GitHub release path." >&2
  exit 2
fi
if [[ -z "$RELEASE_COMMIT_SHA" && "$CODE_REVISION" != "$SOURCE_REVISION" ]]; then
  echo "CODE_REVISION does not match the exact Cloud Build upload context." >&2
  echo "Expected ${SOURCE_REVISION}; refusing an incorrectly correlated release." >&2
  exit 2
fi
if [[ "$IMAGE_TAG" != "$CODE_REVISION" ]]; then
  echo "IMAGE_TAG must exactly match CODE_REVISION for an immutable release." >&2
  exit 2
fi
if [[ "$RUN_BOOTSTRAP_ON_RELEASE" != "true" && "$RUN_BOOTSTRAP_ON_RELEASE" != "false" ]]; then
  echo "RUN_BOOTSTRAP_ON_RELEASE must be true or false." >&2
  exit 2
fi
if [[ "$RELEASE_IMAGE_BUILT" != "true" && "$RELEASE_IMAGE_BUILT" != "false" ]]; then
  echo "RELEASE_IMAGE_BUILT must be true or false." >&2
  exit 2
fi
if [[ ! "$BILLING_ACCOUNT_OTHER_ACTIVE_SECRET_VERSIONS" =~ ^[0-9]+$ ]]; then
  echo "BILLING_ACCOUNT_OTHER_ACTIVE_SECRET_VERSIONS must be a current numeric receipt." >&2
  exit 2
fi
if [[ ! "$IMAGE_TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "IMAGE_TAG is not a valid immutable container tag." >&2
  exit 2
fi
if [[ -n "$RELEASE_IMAGE_DIGEST" \
  && ! "$RELEASE_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "RELEASE_IMAGE_DIGEST must be an exact sha256 digest." >&2
  exit 2
fi
if [[ "$RELEASE_IMAGE_BUILT" == "true" && -z "$RELEASE_IMAGE_DIGEST" ]]; then
  echo "A workflow-built release requires RELEASE_IMAGE_DIGEST." >&2
  exit 2
fi
if [[ -n "$RELEASE_IMAGE_DIGEST" ]]; then
  IMAGE="${IMAGE_REPOSITORY}@${RELEASE_IMAGE_DIGEST}"
fi
RELEASE_FAILURE_CLEANUP_ARMED=true
trap scheduler_pause_on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

PROJECT_NUMBER="$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')"
if [[ -z "$PROJECT_NUMBER" ]]; then
  echo "Google Cloud did not report a project number for ${GCP_PROJECT_ID}." >&2
  exit 2
fi
EXPECTED_DEFAULT_ORIGIN="https://${SERVICE_NAME}-${PROJECT_NUMBER}.${GCP_REGION}.run.app"
if [[ "$PUBLIC_API_ORIGIN" == https://*.run.app && "$PUBLIC_API_ORIGIN" != "$EXPECTED_DEFAULT_ORIGIN" ]]; then
  echo "The deterministic Cloud Run origin is ${EXPECTED_DEFAULT_ORIGIN}." >&2
  echo "Refusing the different run.app origin ${PUBLIC_API_ORIGIN}." >&2
  exit 2
fi

python3 scripts/release/secret_version_guard.py check \
  --project "$GCP_PROJECT_ID" \
  --pending 0 \
  --settled-ceiling 6 \
  --rotation-ceiling 8 \
  --external-active "$BILLING_ACCOUNT_OTHER_ACTIVE_SECRET_VERSIONS" \
  --allow-candidates

resolve_enabled_secret_version() {
  local secret_name="$1"
  local metadata
  metadata="$(gcloud secrets versions describe latest \
    --secret "$secret_name" \
    --project "$GCP_PROJECT_ID" \
    --format=json)"
  python3 -c '
import json, sys
item = json.load(sys.stdin)
name = item.get("name", "")
state = item.get("state", "")
version = name.rsplit("/", 1)[-1]
if state != "ENABLED" or not version.isdigit():
    raise SystemExit(2)
print(version)
' <<<"$metadata"
}

WEB_SECRET_VERSION="$(resolve_enabled_secret_version "$WEB_SECRET_NAME")"
MIGRATE_SECRET_VERSION="$(resolve_enabled_secret_version "$MIGRATE_SECRET_NAME")"
JOBS_SECRET_VERSION="$(resolve_enabled_secret_version "$JOBS_SECRET_NAME")"
echo "Production secret versions resolved to exact numeric references; payloads were not read."

REQUEST_LOG_EXCLUSION="exclude-cloud-run-request-logs"
REQUEST_LOG_FILTER='log_id("run.googleapis.com/requests")'
if gcloud logging sinks describe _Default \
  --project "$GCP_PROJECT_ID" \
  --format=json \
| python3 scripts/release/verify_logging_exclusion.py \
    --name "$REQUEST_LOG_EXCLUSION" \
    --filter "$REQUEST_LOG_FILTER" >/dev/null 2>&1; then
  echo "Cloud Run infrastructure request-log storage exclusion already verified."
elif gcloud logging sinks describe _Default \
  --project "$GCP_PROJECT_ID" \
  --format=json \
| python3 -c \
    'import json, sys; name = sys.argv[1]; sink = json.load(sys.stdin); raise SystemExit(0 if any(item.get("name") == name for item in sink.get("exclusions", [])) else 1)' \
    "$REQUEST_LOG_EXCLUSION"; then
  gcloud logging sinks update _Default \
    --project "$GCP_PROJECT_ID" \
    --update-exclusion="name=${REQUEST_LOG_EXCLUSION},filter=${REQUEST_LOG_FILTER},disabled=" \
    --quiet
else
  gcloud logging sinks update _Default \
    --project "$GCP_PROJECT_ID" \
    --add-exclusion="name=${REQUEST_LOG_EXCLUSION},filter=${REQUEST_LOG_FILTER},description=Do not store raw Cloud Run infrastructure request logs" \
    --quiet
fi
gcloud logging sinks describe _Default \
  --project "$GCP_PROJECT_ID" \
  --format=json \
| python3 scripts/release/verify_logging_exclusion.py \
    --name "$REQUEST_LOG_EXCLUSION" \
    --filter "$REQUEST_LOG_FILTER"

REPOSITORY_SIZE_BYTES="$(python3 scripts/release/artifact_repository_size.py \
  --project "$GCP_PROJECT_ID" \
  --location "$GCP_REGION" \
  --repository "$REPOSITORY")"
if [[ ! "$REPOSITORY_SIZE_BYTES" =~ ^[0-9]+$ ]]; then
  echo "Artifact Registry did not report a numeric repository size." >&2
  exit 3
fi
if (( REPOSITORY_SIZE_BYTES > ARTIFACT_BUDGET_BYTES )); then
  echo "Artifact Registry is ${REPOSITORY_SIZE_BYTES} bytes, above its 1 GB release budget." >&2
  echo "Inspect exact image versions before cleanup; the deploy script never deletes images." >&2
  exit 3
fi
echo "Artifact Registry pre-build size: ${REPOSITORY_SIZE_BYTES} bytes."

if [[ -n "$RELEASE_IMAGE_DIGEST" ]]; then
  IMAGE_DIGEST="$(gcloud artifacts docker images describe "$IMAGE_TAG_REFERENCE" \
    --project "$GCP_PROJECT_ID" --format='value(image_summary.digest)')"
  if [[ "$IMAGE_DIGEST" != "$RELEASE_IMAGE_DIGEST" ]]; then
    echo "The commit-SHA image tag does not resolve to RELEASE_IMAGE_DIGEST." >&2
    exit 3
  fi
  echo "Using workflow-built immutable image ${IMAGE_TAG_REFERENCE}@${IMAGE_DIGEST}."
elif IMAGE_DIGEST="$(gcloud artifacts docker images describe "$IMAGE_TAG_REFERENCE" \
  --project "$GCP_PROJECT_ID" --format='value(image_summary.digest)' 2>/dev/null)" \
  && [[ -n "$IMAGE_DIGEST" ]]; then
  echo "Reusing the existing immutable image tag ${IMAGE_TAG_REFERENCE}."
else
  if (( REPOSITORY_SIZE_BYTES > ARTIFACT_BUDGET_BYTES - NEW_IMAGE_RESERVE_BYTES )); then
    echo "Artifact Registry lacks the budgeted 256 MiB headroom required before a build." >&2
    echo "Current billed bytes: ${REPOSITORY_SIZE_BYTES}; no image was built." >&2
    exit 3
  fi
  gcloud builds submit \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --config ops/container/cloudbuild.yaml \
    --substitutions "_IMAGE=${IMAGE_TAG_REFERENCE},_CODE_REVISION=${CODE_REVISION}" \
    --quiet \
    .
  IMAGE_BUILT_THIS_RELEASE=true
  IMAGE_DIGEST="$(gcloud artifacts docker images describe "$IMAGE_TAG_REFERENCE" \
    --project "$GCP_PROJECT_ID" --format='value(image_summary.digest)')"
  if [[ ! "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Cloud Build did not produce one verifiable image digest." >&2
    exit 3
  fi
  IMAGE="${IMAGE_REPOSITORY}@${IMAGE_DIGEST}"
  if [[ -n "$SOURCE_REVISION" && "$(python3 scripts/release/source_revision.py)" != "$CODE_REVISION" ]]; then
    echo "The Cloud Build upload context changed while the image was building." >&2
    echo "No Cloud Run resource has been changed; restart the release." >&2
    delete_unserved_release_build "$IMAGE"
    exit 3
  fi
fi
if [[ ! "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Artifact Registry did not report a valid image digest for ${IMAGE_TAG_REFERENCE}." >&2
  exit 3
fi
IMAGE="${IMAGE_REPOSITORY}@${IMAGE_DIGEST}"

REPOSITORY_SIZE_BYTES_AFTER="$(python3 scripts/release/artifact_repository_size.py \
  --project "$GCP_PROJECT_ID" \
  --location "$GCP_REGION" \
  --repository "$REPOSITORY")"
if [[ ! "$REPOSITORY_SIZE_BYTES_AFTER" =~ ^[0-9]+$ ]]; then
  echo "Artifact Registry did not report a numeric repository size." >&2
  delete_unserved_release_build "$IMAGE"
  exit 3
fi
if (( REPOSITORY_SIZE_BYTES_AFTER > ARTIFACT_BUDGET_BYTES )); then
  echo "Artifact Registry is ${REPOSITORY_SIZE_BYTES_AFTER} bytes, above its 1 GB release budget." >&2
  echo "No Cloud Run resource has been changed." >&2
  delete_unserved_release_build "$IMAGE"
  exit 3
fi
echo "Artifact Registry post-build size: ${REPOSITORY_SIZE_BYTES_AFTER} bytes (1 GB budget)."

SERVICE_PREVIOUS_STATE="$(gcloud run services list \
  --project "$GCP_PROJECT_ID" \
  --region "$GCP_REGION" \
  --format=json \
  | python3 scripts/release/service_release.py --discover-name "$SERVICE_NAME")"
if [[ "$SERVICE_PREVIOUS_STATE" == "PRESENT" ]]; then
  SERVICE_BEFORE_JSON="$(gcloud run services describe "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --format=json)"
  PREVIOUS_SERVING_REVISION="$(python3 scripts/release/service_release.py \
    --serving-revision <<<"$SERVICE_BEFORE_JSON")"
  PREVIOUS_SERVING_IMAGE="$(gcloud run revisions describe "$PREVIOUS_SERVING_REVISION" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --format='value(spec.containers[0].image)')"
  if [[ "$PREVIOUS_SERVING_IMAGE" != "${IMAGE_REPOSITORY}@sha256:"* ]]; then
    echo "The serving rollback revision is not pinned to the expected Artifact Registry package." >&2
    exit 3
  fi
  gcloud artifacts docker tags add \
    "$PREVIOUS_SERVING_IMAGE" "${IMAGE_REPOSITORY}:production-rollback" \
    --project "$GCP_PROJECT_ID" \
    --quiet
elif [[ "$SERVICE_PREVIOUS_STATE" != "ABSENT" ]]; then
  echo "Unexpected service discovery state: ${SERVICE_PREVIOUS_STATE}." >&2
  exit 3
fi

gcloud artifacts repositories set-cleanup-policies "$REPOSITORY" \
  --project "$GCP_PROJECT_ID" \
  --location "$GCP_REGION" \
  --policy ops/deployment/artifact-cleanup-policy.json \
  --no-dry-run \
  --quiet

# Capture scheduling intent and stop executions before replacing any job
# image. A list failure aborts through pipefail and cannot be mistaken for an
# absent job.
SCHEDULER_PREVIOUS_STATE="$(
  gcloud scheduler jobs list \
    --project "$GCP_PROJECT_ID" \
    --location "$SCHEDULER_REGION" \
    --format=json \
  | python3 scripts/release/verify_scheduler.py \
      --discover-name "$SCHEDULER_JOB_NAME"
)"
if [[ "$SCHEDULER_PREVIOUS_STATE" != "ABSENT" ]]; then
  SCHEDULER_PREVIOUS_DESCRIPTION="$(scheduler_current_description)"
fi
case "$SCHEDULER_PREVIOUS_STATE" in
  ENABLED)
    SCHEDULER_RESUME_AFTER_RELEASE=true
    SCHEDULER_RELEASE_DESCRIPTION="$SCHEDULER_RESUME_MARKER"
    ;;
  PAUSED)
    if [[ "$SCHEDULER_PREVIOUS_DESCRIPTION" == "$SCHEDULER_RESUME_MARKER" ]]; then
      # A failed release deliberately left the job paused. The marker preserves
      # the pre-failure enabled intent for this retry.
      SCHEDULER_RESUME_AFTER_RELEASE=true
      SCHEDULER_RELEASE_DESCRIPTION="$SCHEDULER_RESUME_MARKER"
    else
      SCHEDULER_RESUME_AFTER_RELEASE=false
      SCHEDULER_RELEASE_DESCRIPTION="$SCHEDULER_STABLE_DESCRIPTION"
    fi
    ;;
  ABSENT)
    # A newly created production schedule is intended to become enabled only
    # after the first complete release succeeds.
    SCHEDULER_RESUME_AFTER_RELEASE=true
    SCHEDULER_RELEASE_DESCRIPTION="$SCHEDULER_RESUME_MARKER"
    ;;
  *)
    echo "Refusing a release from Scheduler state ${SCHEDULER_PREVIOUS_STATE}." >&2
    exit 3
    ;;
esac

snapshot_release_resources

if [[ "$SCHEDULER_PREVIOUS_STATE" == "ABSENT" ]]; then
  gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
    --project "$GCP_PROJECT_ID" \
    --location "$SCHEDULER_REGION" \
    --schedule "$SCHEDULER_INERT_CREATE_SCHEDULE" \
    --time-zone Etc/UTC \
    --uri "$SCHEDULER_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_ACCOUNT" \
    --description "$SCHEDULER_RESUME_MARKER" \
    --quiet
elif [[ "$SCHEDULER_PREVIOUS_STATE" == "ENABLED" ]]; then
  gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME" \
    --project "$GCP_PROJECT_ID" \
    --location "$SCHEDULER_REGION" \
    --description "$SCHEDULER_RESUME_MARKER" \
    --quiet
fi
if [[ "$SCHEDULER_RESUME_AFTER_RELEASE" == "true" \
  && "$(scheduler_current_description)" != "$SCHEDULER_RESUME_MARKER" ]]; then
  echo "CRITICAL: unable to persist Scheduler resume intent before pausing." >&2
  exit 3
fi

# Arm the fail-closed pause only after enabled intent is durable. Otherwise a
# marker write/read-back failure could pause an enabled job without leaving the
# next release enough state to know that it must be resumed.
SCHEDULER_RELEASE_GUARD_ACTIVE=true
if [[ "$SCHEDULER_PREVIOUS_STATE" != "PAUSED" ]]; then
  gcloud scheduler jobs pause "$SCHEDULER_JOB_NAME" \
    --project "$GCP_PROJECT_ID" \
    --location "$SCHEDULER_REGION" \
    --quiet
fi
gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" \
  --project "$GCP_PROJECT_ID" \
  --location "$SCHEDULER_REGION" \
  --format=json \
| python3 scripts/release/verify_scheduler.py --state PAUSED
echo "Scheduler release guard armed from prior state ${SCHEDULER_PREVIOUS_STATE}."

mark_release_job_mutation illinicover-migrate
gcloud run jobs deploy illinicover-migrate \
  --project "$GCP_PROJECT_ID" \
  --region "$GCP_REGION" \
  --image "$IMAGE" \
  --service-account "illinicover-migrate@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "^@^DJANGO_SETTINGS_MODULE=config.settings.production@DEPLOYMENT_ENVIRONMENT=production@DATABASE_MODE=direct@PUBLIC_API_ORIGIN=${PUBLIC_API_ORIGIN}@CODE_REVISION=${CODE_REVISION}" \
  --set-secrets "ILLINICOVER_SECRETS_JSON=${MIGRATE_SECRET_NAME}:${MIGRATE_SECRET_VERSION}" \
  --command python \
  --args server/manage.py,migrate,--noinput,--settings=config.settings.production \
  --cpu 1 \
  --memory 512Mi \
  --task-timeout 10m \
  --max-retries 1 \
  --tasks 1 \
  --quiet

mark_release_job_mutation illinicover-bootstrap
gcloud run jobs deploy illinicover-bootstrap \
  --project "$GCP_PROJECT_ID" \
  --region "$GCP_REGION" \
  --image "$IMAGE" \
  --service-account "illinicover-jobs@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "^@^DJANGO_SETTINGS_MODULE=config.settings.production@DEPLOYMENT_ENVIRONMENT=production@DATABASE_MODE=pooled@PUBLIC_API_ORIGIN=${PUBLIC_API_ORIGIN}@CODE_REVISION=${CODE_REVISION}" \
  --set-secrets "ILLINICOVER_SECRETS_JSON=${JOBS_SECRET_NAME}:${JOBS_SECRET_VERSION}" \
  --command python \
  --args server/manage.py,bootstrap_beta,--settings=config.settings.production \
  --cpu 1 \
  --memory 512Mi \
  --task-timeout 15m \
  --max-retries 1 \
  --tasks 1 \
  --quiet

mark_release_job_mutation illinicover-refresh
gcloud run jobs deploy illinicover-refresh \
  --project "$GCP_PROJECT_ID" \
  --region "$GCP_REGION" \
  --image "$IMAGE" \
  --service-account "illinicover-jobs@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "^@^DJANGO_SETTINGS_MODULE=config.settings.production@DEPLOYMENT_ENVIRONMENT=production@DATABASE_MODE=pooled@PUBLIC_API_ORIGIN=${PUBLIC_API_ORIGIN}@CODE_REVISION=${CODE_REVISION}" \
  --set-secrets "ILLINICOVER_SECRETS_JSON=${JOBS_SECRET_NAME}:${JOBS_SECRET_VERSION}" \
  --command python \
  --args server/manage.py,refresh_context,--settings=config.settings.production \
  --cpu 1 \
  --memory 512Mi \
  --task-timeout 15m \
  --max-retries 1 \
  --tasks 1 \
  --quiet

mark_release_job_mutation illinicover-nightly
gcloud run jobs deploy illinicover-nightly \
  --project "$GCP_PROJECT_ID" \
  --region "$GCP_REGION" \
  --image "$IMAGE" \
  --service-account "illinicover-jobs@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "^@^DJANGO_SETTINGS_MODULE=config.settings.production@DEPLOYMENT_ENVIRONMENT=production@DATABASE_MODE=pooled@PUBLIC_API_ORIGIN=${PUBLIC_API_ORIGIN}@CODE_REVISION=${CODE_REVISION}" \
  --set-secrets "ILLINICOVER_SECRETS_JSON=${JOBS_SECRET_NAME}:${JOBS_SECRET_VERSION}" \
  --command python \
  --args server/manage.py,nightly,--settings=config.settings.production \
  --cpu 1 \
  --memory 512Mi \
  --task-timeout 15m \
  --max-retries 1 \
  --tasks 1 \
  --quiet

verify_job_release() {
  local job="$1"
  local database_mode="$2"
  local secret_name="$3"
  local secret_version="$4"
  gcloud run jobs describe "$job" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --format=json \
  | python3 scripts/release/verify_release_resource.py \
      --name "$job" \
      --expected-image "$IMAGE" \
      --expected-revision "$CODE_REVISION" \
      --expected-env "DATABASE_MODE=${database_mode}" \
      --expected-env "DEPLOYMENT_ENVIRONMENT=production" \
      --expected-secret "ILLINICOVER_SECRETS_JSON=${secret_name}:${secret_version}"
}

verify_job_release illinicover-migrate direct "$MIGRATE_SECRET_NAME" "$MIGRATE_SECRET_VERSION"
verify_job_release illinicover-bootstrap pooled "$JOBS_SECRET_NAME" "$JOBS_SECRET_VERSION"
verify_job_release illinicover-refresh pooled "$JOBS_SECRET_NAME" "$JOBS_SECRET_VERSION"
verify_job_release illinicover-nightly pooled "$JOBS_SECRET_NAME" "$JOBS_SECRET_VERSION"

gcloud run jobs add-iam-policy-binding illinicover-nightly \
  --project "$GCP_PROJECT_ID" \
  --region "$GCP_REGION" \
  --member "$SCHEDULER_MEMBER" \
  --role roles/run.invoker \
  --quiet
if [[ "$(gcloud projects get-iam-policy "$GCP_PROJECT_ID" \
  --flatten='bindings[].members' \
  --filter="bindings.role=roles/run.invoker AND bindings.members=${SCHEDULER_MEMBER}" \
  --format='value(bindings.members)')" == "$SCHEDULER_MEMBER" ]]; then
  gcloud projects remove-iam-policy-binding "$GCP_PROJECT_ID" \
    --member "$SCHEDULER_MEMBER" \
    --role roles/run.invoker \
    --condition=None \
    --quiet
fi
if [[ "$(gcloud run jobs get-iam-policy illinicover-nightly \
  --project "$GCP_PROJECT_ID" \
  --region "$GCP_REGION" \
  --flatten='bindings[].members' \
  --filter="bindings.role=roles/run.invoker AND bindings.members=${SCHEDULER_MEMBER}" \
  --format='value(bindings.members)')" != "$SCHEDULER_MEMBER" ]]; then
  echo "Nightly job is missing its resource-scoped Scheduler invoker binding." >&2
  exit 3
fi
if [[ -n "$(gcloud projects get-iam-policy "$GCP_PROJECT_ID" \
  --flatten='bindings[].members' \
  --filter="bindings.role=roles/run.invoker AND bindings.members=${SCHEDULER_MEMBER}" \
  --format='value(bindings.members)')" ]]; then
  echo "Project-wide Cloud Run invoker access still exists for ${SCHEDULER_ACCOUNT}." >&2
  exit 3
fi

gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME" \
  --project "$GCP_PROJECT_ID" \
  --location "$SCHEDULER_REGION" \
  --schedule "$SCHEDULER_SCHEDULE" \
  --time-zone "$SCHEDULER_TIME_ZONE" \
  --uri "$SCHEDULER_URI" \
  --http-method POST \
  --oauth-service-account-email "$SCHEDULER_ACCOUNT" \
  --description "$SCHEDULER_RELEASE_DESCRIPTION" \
  --quiet

gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" \
  --project "$GCP_PROJECT_ID" \
  --location "$SCHEDULER_REGION" \
  --format=json \
| python3 scripts/release/verify_scheduler.py \
    --schedule "$SCHEDULER_SCHEDULE" \
    --time-zone "$SCHEDULER_TIME_ZONE" \
    --uri "$SCHEDULER_URI" \
    --service-account "$SCHEDULER_ACCOUNT" \
    --state PAUSED

gcloud run jobs execute illinicover-migrate \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --wait --quiet
if [[ "$RUN_BOOTSTRAP_ON_RELEASE" == "true" ]]; then
  gcloud run jobs execute illinicover-bootstrap \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --wait --quiet
fi

CANDIDATE_TAG="candidate"
DEPLOY_TRAFFIC_ARGS=(--no-traffic --allow-unauthenticated)
if [[ "$SERVICE_PREVIOUS_STATE" == "ABSENT" ]]; then
  # Cloud Run cannot create a service with zero serving revisions. The
  # deploy-health-check remains the first gate; after creation the same
  # candidate and stable-origin probes run before the release is accepted.
  DEPLOY_TRAFFIC_ARGS=(--no-allow-unauthenticated)
  SERVICE_PUBLIC_ACCESS_PENDING=true
fi
SERVICE_MUTATION_STARTED=true
gcloud run deploy "$SERVICE_NAME" \
  --project "$GCP_PROJECT_ID" \
  --region "$GCP_REGION" \
  --image "$IMAGE" \
  --execution-environment gen2 \
  "${DEPLOY_TRAFFIC_ARGS[@]}" \
  --tag "$CANDIDATE_TAG" \
  --service-account "illinicover-web@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "^@^DJANGO_SETTINGS_MODULE=config.settings.production@DEPLOYMENT_ENVIRONMENT=production@DATABASE_MODE=pooled@TRUSTED_XFF_PROXY_HOPS=0@ALLOWED_HOSTS=.run.app,api.illinicover.com,localhost,127.0.0.1@CSRF_TRUSTED_ORIGINS=https://*.run.app,https://api.illinicover.com@PUBLIC_API_ORIGIN=${PUBLIC_API_ORIGIN}@CODE_REVISION=${CODE_REVISION}" \
  --set-secrets "ILLINICOVER_SECRETS_JSON=${WEB_SECRET_NAME}:${WEB_SECRET_VERSION}" \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 40 \
  --timeout 30 \
  --min 0 \
  --max 3 \
  --startup-probe 'httpGet.path=/health/live,httpGet.port=8080,periodSeconds=2,timeoutSeconds=1,failureThreshold=15' \
  --liveness-probe 'httpGet.path=/health/live,httpGet.port=8080,periodSeconds=30,timeoutSeconds=2,failureThreshold=3' \
  --readiness-probe 'httpGet.path=/health/live,httpGet.port=8080,periodSeconds=5,timeoutSeconds=2,failureThreshold=3,successThreshold=1' \
  --deploy-health-check \
  --cpu-throttling \
  --no-cpu-boost \
  --quiet

SERVICE_AFTER_DEPLOY_JSON="$(gcloud run services describe "$SERVICE_NAME" \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json)"
SERVICE_URL="$(python3 -c \
  'import json, sys; value = json.load(sys.stdin).get("status", {}).get("url", ""); print(value)' \
  <<<"$SERVICE_AFTER_DEPLOY_JSON")"
if [[ -z "$SERVICE_URL" ]]; then
  echo "Cloud Run did not report a service URL." >&2
  exit 3
fi
python3 scripts/release/verify_release_resource.py \
    --name "$SERVICE_NAME" \
    --expected-image "$IMAGE" \
    --expected-revision "$CODE_REVISION" \
    --expected-env "DATABASE_MODE=pooled" \
    --expected-env "DEPLOYMENT_ENVIRONMENT=production" \
    --expected-secret "ILLINICOVER_SECRETS_JSON=${WEB_SECRET_NAME}:${WEB_SECRET_VERSION}" \
    <<<"$SERVICE_AFTER_DEPLOY_JSON"
CANDIDATE_REVISION="$(python3 scripts/release/service_release.py \
  --tag-revision "$CANDIDATE_TAG" <<<"$SERVICE_AFTER_DEPLOY_JSON")"
CANDIDATE_URL="$(python3 scripts/release/service_release.py \
  --tag-url "$CANDIDATE_TAG" <<<"$SERVICE_AFTER_DEPLOY_JSON")"

probe_json_status() {
  local origin="$1"
  local path="$2"
  local expected="$3"
  local response
  response="$(curl --fail --silent --show-error --retry 5 --retry-all-errors \
    --retry-delay 2 --connect-timeout 5 --max-time 30 "${origin}${path}")"
  python3 -c \
    'import json, sys; payload = json.load(sys.stdin); raise SystemExit(0 if payload.get("status") == sys.argv[1] else 1)' \
    "$expected" <<<"$response"
}

probe_origin() {
  local origin="$1"
  local privacy
  probe_json_status "$origin" /health/live ok
  probe_json_status "$origin" /health/ready ready
  probe_json_status "$origin" /api/v2/status ok
  privacy="$(curl --fail --silent --show-error --retry 5 --retry-all-errors \
    --retry-delay 2 --connect-timeout 5 --max-time 30 "${origin}/privacy")"
  if [[ "$privacy" != *"IlliniCover privacy policy"* ]]; then
    echo "Privacy policy smoke probe failed at ${origin}." >&2
    return 1
  fi
  curl --fail --silent --show-error --retry 5 --retry-all-errors \
    --retry-delay 2 --connect-timeout 5 --max-time 30 \
    "${origin}/static/admin/css/base.css" >/dev/null
}

probe_authenticated_origin() {
  local origin="$1"
  local audience="$2"
  local identity_token
  identity_token="$(gcloud auth print-identity-token --audiences="$audience")"
  [[ -n "$identity_token" ]] || {
    echo "Unable to mint a private first-release probe token." >&2
    return 1
  }
  probe_authenticated_json_status() {
    local path="$1"
    local expected="$2"
    local response
    response="$(curl --fail --silent --show-error --retry 5 --retry-all-errors \
      --retry-delay 2 --connect-timeout 5 --max-time 30 \
      --header "Authorization: Bearer ${identity_token}" "${origin}${path}")"
    python3 -c \
      'import json, sys; payload = json.load(sys.stdin); raise SystemExit(0 if payload.get("status") == sys.argv[1] else 1)' \
      "$expected" <<<"$response"
  }
  probe_authenticated_json_status /health/live ok
  probe_authenticated_json_status /health/ready ready
}

if [[ "$SERVICE_PREVIOUS_STATE" == "PRESENT" ]]; then
  probe_origin "$CANDIDATE_URL"
else
  probe_authenticated_origin "$CANDIDATE_URL" "$SERVICE_URL"
fi

if [[ "$SERVICE_PREVIOUS_STATE" == "PRESENT" ]]; then
  # Arm rollback before the traffic mutation so an interrupted or failed
  # update cannot leave a partially promoted release without a restore.
  RELEASE_TRAFFIC_SWITCHED=true
  gcloud run services update-traffic "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --to-revisions "${CANDIDATE_REVISION}=100" \
    --quiet
  SERVING_AFTER_PROMOTION="$(gcloud run services describe "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --format=json \
    | python3 scripts/release/service_release.py --serving-revision)"
  if [[ "$SERVING_AFTER_PROMOTION" != "$CANDIDATE_REVISION" ]]; then
    echo "Cloud Run did not route 100 percent of production traffic to the candidate." >&2
    exit 3
  fi
fi

if [[ "$SERVICE_PREVIOUS_STATE" == "PRESENT" ]]; then
  probe_origin "$SERVICE_URL"
  if [[ "$PUBLIC_API_ORIGIN" != "$SERVICE_URL" ]]; then
    probe_origin "$PUBLIC_API_ORIGIN"
  fi
else
  probe_authenticated_origin "$SERVICE_URL" "$SERVICE_URL"
fi

if [[ "$SERVICE_PREVIOUS_STATE" == "ABSENT" ]]; then
  gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --member allUsers \
    --role roles/run.invoker \
    --quiet
  if [[ "$(gcloud run services get-iam-policy "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" \
    --region "$GCP_REGION" \
    --flatten='bindings[].members' \
    --filter='bindings.role=roles/run.invoker AND bindings.members=allUsers' \
    --format='value(bindings.members)')" != "allUsers" ]]; then
    echo "First release did not acquire its exact public invoker binding." >&2
    exit 3
  fi
  probe_origin "$SERVICE_URL"
  if [[ "$PUBLIC_API_ORIGIN" != "$SERVICE_URL" ]]; then
    probe_origin "$PUBLIC_API_ORIGIN"
  fi
  SERVICE_PUBLIC_ACCESS_PENDING=false
fi

gcloud artifacts docker tags add \
  "$IMAGE" "${IMAGE_REPOSITORY}:production-serving" \
  --project "$GCP_PROJECT_ID" \
  --quiet

if [[ "$SCHEDULER_RESUME_AFTER_RELEASE" == "true" ]]; then
  gcloud scheduler jobs resume "$SCHEDULER_JOB_NAME" \
    --project "$GCP_PROJECT_ID" \
    --location "$SCHEDULER_REGION" \
    --quiet
  gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" \
    --project "$GCP_PROJECT_ID" \
    --location "$SCHEDULER_REGION" \
    --format=json \
  | python3 scripts/release/verify_scheduler.py --state ENABLED
  echo "Scheduler resumed after the complete release and smoke probes."
else
  gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" \
    --project "$GCP_PROJECT_ID" \
    --location "$SCHEDULER_REGION" \
    --format=json \
  | python3 scripts/release/verify_scheduler.py --state PAUSED
  echo "Scheduler remains intentionally paused as it was before the release."
fi
SCHEDULER_RELEASE_GUARD_ACTIVE=false
RELEASE_TRAFFIC_SWITCHED=false
RELEASE_FAILURE_CLEANUP_ARMED=false
trap - EXIT HUP INT TERM
cleanup_release_state_directory
if [[ "$SCHEDULER_RESUME_AFTER_RELEASE" == "true" ]]; then
  # Clear the recovery marker only after the accepted release has disarmed all
  # rollback traps. If this metadata update fails, the still-enabled schedule
  # safely retains its resume intent for the next release.
  gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME" \
    --project "$GCP_PROJECT_ID" \
    --location "$SCHEDULER_REGION" \
    --description "$SCHEDULER_STABLE_DESCRIPTION" \
    --quiet
  if [[ "$(scheduler_current_description)" != "$SCHEDULER_STABLE_DESCRIPTION" ]]; then
    echo "CRITICAL: unable to clear the Scheduler release-resume marker." >&2
    exit 3
  fi
fi

# The accepted service and all accepted jobs now pin the exact retained
# versions. Disable/read-back/destroy any superseded candidates only after the
# release trap is disarmed, so cleanup failure cannot roll traffic onto a
# revision whose former secret version has already been retired.
python3 scripts/release/secret_version_guard.py retire \
  --project "$GCP_PROJECT_ID" \
  --keep "${WEB_SECRET_NAME}=${WEB_SECRET_VERSION}" \
  --keep "${MIGRATE_SECRET_NAME}=${MIGRATE_SECRET_VERSION}" \
  --keep "${JOBS_SECRET_NAME}=${JOBS_SECRET_VERSION}" \
  --execute
python3 scripts/release/secret_version_guard.py check \
  --project "$GCP_PROJECT_ID" \
  --pending 0 \
  --settled-ceiling 6 \
  --rotation-ceiling 8 \
  --external-active "$BILLING_ACCOUNT_OTHER_ACTIVE_SECRET_VERSIONS"

echo "Deployed immutable image ${IMAGE} as ${SERVICE_NAME}."
echo "Code revision: ${CODE_REVISION}."
if [[ "$RUN_BOOTSTRAP_ON_RELEASE" == "true" ]]; then
  echo "Migration and explicit bootstrap succeeded; nightly was not executed."
else
  echo "Migration succeeded; bootstrap and nightly were not executed."
fi
