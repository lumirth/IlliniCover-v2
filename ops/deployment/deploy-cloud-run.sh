#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${GCP_REGION:?Set GCP_REGION}"
: "${ARTIFACT_REPOSITORY:?Set ARTIFACT_REPOSITORY}"
: "${PUBLIC_API_ORIGIN:?Set PUBLIC_API_ORIGIN}"
: "${CODE_REVISION:?Set CODE_REVISION}"
: "${IMAGE:?Set IMAGE to an Artifact Registry digest reference}"

service="${CLOUD_RUN_SERVICE:-illinicover-api}"
web_secret="${WEB_SECRET_NAME:-illinicover-web}"
migrate_secret="${MIGRATE_SECRET_NAME:-illinicover-migrate}"
reconcile_job="illinicover-reconcile"
scheduler_region="us-east4"
scheduler_identity="illinicover-scheduler@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
image_repository="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${ARTIFACT_REPOSITORY}/backend"
attempt="${GITHUB_RUN_ATTEMPT:-1}"
run_id="${GITHUB_RUN_ID:?Set GITHUB_RUN_ID to the GitHub Actions run identifier}"
suffix="sha-${CODE_REVISION:0:10}-${run_id}-${attempt}"
candidate="${service}-${suffix}"
tag="candidate"
candidate_started=false
previous_revision=""
image_digest="${IMAGE#"${image_repository}@"}"
prealpha_cutover="${PREALPHA_CUTOVER:-false}"

[[ "$GCP_PROJECT_ID" != "lukashermes" ]] || {
  echo "Refusing to deploy into the unrelated lukashermes project." >&2
  exit 2
}
[[ "$CODE_REVISION" =~ ^[0-9a-f]{40}$ ]] || {
  echo "CODE_REVISION must be the exact lowercase Git commit SHA." >&2
  exit 2
}
[[ "$attempt" =~ ^[1-9][0-9]*$ ]] || {
  echo "GITHUB_RUN_ATTEMPT must be a positive integer." >&2
  exit 2
}
[[ "$run_id" =~ ^[1-9][0-9]*$ ]] || {
  echo "GITHUB_RUN_ID must be a positive integer." >&2
  exit 2
}
[[ "$IMAGE" == "${image_repository}@${image_digest}" \
  && "$image_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "IMAGE must be an exact digest from ${image_repository}." >&2
  exit 2
}
[[ "$PUBLIC_API_ORIGIN" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?$ ]] || {
  echo "PUBLIC_API_ORIGIN must be a path-free HTTPS origin." >&2
  exit 2
}
[[ "$prealpha_cutover" == true || "$prealpha_cutover" == false ]] || {
  echo "PREALPHA_CUTOVER must be true or false." >&2
  exit 2
}

secret_version() {
  local metadata name state version
  metadata="$(gcloud secrets versions describe latest \
    --project "$GCP_PROJECT_ID" --secret "$1" --format='value(name,state)')"
  read -r name state <<<"$metadata"
  version="${name##*/}"
  [[ "$version" =~ ^[1-9][0-9]*$ && "$state" == "ENABLED" ]] || {
    echo "Secret $1 has no enabled numeric latest version." >&2
    return 2
  }
  printf '%s\n' "$version"
}

serving_revision() {
  gcloud run services describe "$service" \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json \
  | python3 -c 'import json,sys
rows=json.load(sys.stdin).get("status",{}).get("traffic",[])
served={}
for row in rows:
    if row.get("percent",0)>0:
        served[row["revisionName"]]=served.get(row["revisionName"],0)+row["percent"]
valid=[name for name,percent in served.items() if percent==100]
if len(valid)!=1 or len(served)!=1: raise SystemExit(2)
print(valid[0])'
}

service_url() {
  gcloud run services describe "$service" \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format='value(status.url)'
}

service_presence() {
  local found
  found="$(gcloud run services list --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
    --filter="metadata.name=${service}" --format='value(metadata.name)')" || return 2
  if [[ "$found" == "$service" ]]; then printf 'present\n';
  elif [[ -z "$found" ]]; then printf 'absent\n';
  else return 2; fi
}

revision_presence() {
  local found
  found="$(gcloud run revisions list --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
    --filter="metadata.name=$1" --format='value(metadata.name)')" || return 2
  if [[ "$found" == "$1" ]]; then printf 'present\n';
  elif [[ -z "$found" ]]; then printf 'absent\n';
  else return 2; fi
}

run_job_presence() {
  local found
  found="$(gcloud run jobs list --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
    --filter="metadata.name=$1" --format='value(metadata.name)')" || return 2
  if [[ "$found" == "$1" ]]; then printf 'present\n';
  elif [[ -z "$found" ]]; then printf 'absent\n';
  else return 2; fi
}

scheduler_presence() {
  local names row count=0
  names="$(gcloud scheduler jobs list --project "$GCP_PROJECT_ID" \
    --location "$scheduler_region" --format='value(name)')" || return 2
  while IFS= read -r row; do
    [[ "${row##*/}" == "$1" ]] && ((count += 1))
  done <<<"$names"
  if [[ "$count" == 1 ]]; then printf 'present\n';
  elif [[ "$count" == 0 ]]; then printf 'absent\n';
  else return 2; fi
}

tagged_url() {
  gcloud run services describe "$service" \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json \
  | python3 -c 'import json,sys
tag=sys.argv[1]
rows=[row for row in json.load(sys.stdin).get("status",{}).get("traffic",[]) if row.get("tag")==tag]
if len(rows)!=1 or not rows[0].get("url","").startswith("https://"): raise SystemExit(2)
print(rows[0]["url"])' "$tag"
}

tagged_revision() {
  gcloud run services describe "$service" \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json \
  | python3 -c 'import json,sys
tag=sys.argv[1]
rows=[row for row in json.load(sys.stdin).get("status",{}).get("traffic",[]) if row.get("tag")==tag]
if len(rows)>1: raise SystemExit(2)
if rows: print(rows[0]["revisionName"])' "$tag"
}

request_json() {
  local origin="$1" path="$2" token="${3:-}" args
  args=(--fail --silent --show-error --retry 5 --retry-all-errors
    --retry-delay 2 --connect-timeout 5 --max-time 30)
  if [[ -n "$token" ]]; then
    args+=(--header "Authorization: Bearer ${token}")
  fi
  curl "${args[@]}" "${origin}${path}"
}

probe() {
  local origin="$1" path="$2" expected="$3" token="${4:-}"
  request_json "$origin" "$path" "$token" \
  | python3 -c 'import json,sys
payload=json.load(sys.stdin)
raise SystemExit(0 if payload.get("status")==sys.argv[1] else 1)' "$expected"
}

probe_origin() {
  local origin="$1" token="${2:-}"
  probe "$origin" /health/live ok "$token"
  probe "$origin" /health/ready ready "$token"
  probe "$origin" /api/status ok "$token"
  request_json "$origin" /api/cover "$token" \
  | python3 -c 'import json,sys
rows=json.load(sys.stdin).get("venues",[])
valid=rows and any(row.get("cover",{}).get("price",{}).get("kind") in {"single","range"} for row in rows)
raise SystemExit(0 if valid else 1)'
  request_json "$origin" /api/deals "$token" \
  | python3 -c 'import json,sys
rows=json.load(sys.stdin).get("venues",[])
raise SystemExit(0 if rows and any(row.get("deals") for row in rows) else 1)'
}

verify_public_invocation() {
  gcloud run services get-iam-policy "$service" \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json \
  | python3 -c 'import json,sys
expected=sys.argv[1]=="true"
bindings=json.load(sys.stdin).get("bindings",[])
members={member for row in bindings if row.get("role")=="roles/run.invoker" for member in row.get("members",[])}
valid="allUsers" in members if expected else not members.intersection({"allUsers","allAuthenticatedUsers"})
raise SystemExit(0 if valid else 1)' "$1"
}

verify_no_project_invoker() {
  gcloud projects get-iam-policy "$GCP_PROJECT_ID" --format=json \
  | python3 -c 'import json,sys
member=sys.argv[1]
bindings=json.load(sys.stdin).get("bindings",[])
invokers={value for row in bindings if row.get("role")=="roles/run.invoker" for value in row.get("members",[])}
found=member in invokers or bool(invokers.intersection({"allUsers","allAuthenticatedUsers"}))
raise SystemExit(1 if found else 0)' "serviceAccount:${scheduler_identity}"
}

cleanup_prealpha_resources() {
  local name presence
  presence="$(scheduler_presence illinicover-nightly)"
  if [[ "$presence" == present ]]; then
    gcloud scheduler jobs delete illinicover-nightly \
      --project "$GCP_PROJECT_ID" --location "$scheduler_region" --quiet
  fi
  [[ "$(scheduler_presence illinicover-nightly)" == absent ]] || {
    echo "Obsolete illinicover-nightly schedule still exists." >&2
    return 3
  }
  for name in illinicover-bootstrap illinicover-nightly illinicover-refresh; do
    presence="$(run_job_presence "$name")"
    if [[ "$presence" == present ]]; then
      gcloud run jobs delete "$name" \
        --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --quiet
    fi
    [[ "$(run_job_presence "$name")" == absent ]] || {
      echo "Obsolete ${name} job still exists." >&2
      return 3
    }
  done
  gcloud projects remove-iam-policy-binding "$GCP_PROJECT_ID" \
    --member "serviceAccount:${scheduler_identity}" --role roles/run.invoker \
    --all --quiet >/dev/null 2>&1 || true
}

rollback_on_failure() {
  local status=$? restored="" tagged="" presence="" presence_status=0 delete_status=0
  trap - EXIT HUP INT TERM
  if [[ "$candidate_started" != true ]]; then
    exit "$status"
  fi
  set +e
  if [[ -n "$previous_revision" ]]; then
    gcloud run services update-traffic "$service" \
      --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
      --to-revisions "${previous_revision}=100" --quiet
    tagged="$(tagged_revision 2>/dev/null)"
    if [[ -n "$tagged" ]]; then
      gcloud run services update-traffic "$service" \
        --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
        --remove-tags "$tag" --quiet
    fi
    presence="$(revision_presence "$candidate")"
    presence_status=$?
    if [[ "$presence_status" == 0 && "$presence" == present ]]; then
      gcloud run revisions delete "$candidate" \
        --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --quiet
    fi
    restored="$(serving_revision 2>/dev/null)"
    tagged="$(tagged_revision 2>/dev/null)"
    presence="$(revision_presence "$candidate")"
    presence_status=$?
    if [[ "$restored" == "$previous_revision" && -z "$tagged" \
      && "$presence_status" == 0 && "$presence" == absent ]]; then
      echo "Release failed; ${previous_revision} was restored and the candidate removed." >&2
    else
      echo "CRITICAL: release failed and candidate cleanup was not verified." >&2
      status=3
    fi
  else
    gcloud run services delete "$service" \
      --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --quiet
    delete_status=$?
    presence="$(service_presence)"
    presence_status=$?
    if [[ "$delete_status" != 0 || "$presence_status" != 0 || "$presence" != absent ]]; then
      echo "CRITICAL: first release failed and remained public." >&2
      status=3
    else
      echo "First release failed; no failed public service remains." >&2
    fi
  fi
  exit "$status"
}
trap rollback_on_failure EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

web_version="$(secret_version "$web_secret")"
migrate_version="$(secret_version "$migrate_secret")"

current_service="$(service_presence)"
if [[ "$current_service" == present ]]; then
  previous_revision="$(serving_revision)"
fi

# This job is only an execution mechanism. It is pinned, read back, and run to
# completion before any candidate can receive traffic.
database_check="python server/manage.py verify_deploy_database --settings=config.settings.production"
if [[ "$prealpha_cutover" == true ]]; then
  database_check+=" --allow-empty"
fi
prepare_command="${database_check} && python server/manage.py migrate --noinput --settings=config.settings.production && python server/manage.py bootstrap --settings=config.settings.production"
gcloud run jobs deploy illinicover-migrate \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --image "$IMAGE" \
  --service-account "illinicover-migrate@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "^@^DJANGO_SETTINGS_MODULE=config.settings.production@DEPLOYMENT_ENVIRONMENT=production@DATABASE_MODE=direct@PUBLIC_API_ORIGIN=${PUBLIC_API_ORIGIN}@CODE_REVISION=${CODE_REVISION}" \
  --set-secrets "ILLINICOVER_SECRETS_JSON=${migrate_secret}:${migrate_version}" \
  --command sh \
  --args=-c,"$prepare_command" \
  --cpu 1 --memory 512Mi --task-timeout 10m --max-retries 1 --tasks 1 --quiet
gcloud run jobs describe illinicover-migrate \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json \
| python3 ops/deployment/verify-cloud-run.py \
    --expected-image "$IMAGE" --expected-revision "$CODE_REVISION" \
    --expected-mode direct --expected-secret "${migrate_secret}:${migrate_version}"
gcloud run jobs execute illinicover-migrate \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --wait --quiet

if [[ "$prealpha_cutover" == true ]]; then
  cleanup_prealpha_resources
fi
verify_no_project_invoker

candidate_started=true
deploy_traffic=(--no-traffic --allow-unauthenticated)
if [[ -z "$previous_revision" ]]; then
  deploy_traffic=()
fi
gcloud run deploy "$service" \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --image "$IMAGE" \
  --revision-suffix "$suffix" --tag "$tag" "${deploy_traffic[@]}" \
  --service-account "illinicover-web@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "^@^DJANGO_SETTINGS_MODULE=config.settings.production@DEPLOYMENT_ENVIRONMENT=production@DATABASE_MODE=pooled@TRUSTED_XFF_PROXY_HOPS=1@ALLOWED_HOSTS=.run.app,api.illinicover.com,localhost,127.0.0.1@CSRF_TRUSTED_ORIGINS=https://*.run.app,https://api.illinicover.com@PUBLIC_API_ORIGIN=${PUBLIC_API_ORIGIN}@CODE_REVISION=${CODE_REVISION}" \
  --set-secrets "ILLINICOVER_SECRETS_JSON=${web_secret}:${web_version}" \
  --cpu 1 --memory 512Mi --concurrency 40 --timeout 30 --min 0 --max 3 \
  --startup-probe 'httpGet.path=/health/live,httpGet.port=8080,periodSeconds=2,timeoutSeconds=1,failureThreshold=15' \
  --liveness-probe 'httpGet.path=/health/live,httpGet.port=8080,periodSeconds=30,timeoutSeconds=2,failureThreshold=3' \
  --deploy-health-check --cpu-throttling --no-cpu-boost --quiet

gcloud run revisions describe "$candidate" \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json \
| python3 ops/deployment/verify-cloud-run.py \
    --expected-image "$IMAGE" --expected-revision "$CODE_REVISION" \
    --expected-mode pooled --expected-secret "${web_secret}:${web_version}"
candidate_url="$(tagged_url)"
if [[ -n "$previous_revision" ]]; then
  probe_origin "$candidate_url"
  gcloud run services update-traffic "$service" \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
    --to-revisions "${candidate}=100" --quiet
else
  verify_public_invocation false
  identity_token="$(gcloud auth print-identity-token --audiences="$(service_url)")"
  [[ -n "$identity_token" ]] || { echo "Could not mint the private candidate probe token." >&2; exit 3; }
  probe_origin "$candidate_url" "$identity_token"
  gcloud run services add-iam-policy-binding "$service" \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
    --member allUsers --role roles/run.invoker --quiet
  verify_public_invocation true
fi
[[ "$(serving_revision)" == "$candidate" ]] || {
  echo "Cloud Run did not promote the candidate revision exclusively." >&2
  exit 3
}
probe_origin "$PUBLIC_API_ORIGIN"
gcloud run services update-traffic "$service" \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --remove-tags "$tag" --quiet
remaining_tag="$(tagged_revision)"
[[ -z "$remaining_tag" && "$(serving_revision)" == "$candidate" ]] || {
  echo "Stable release retained a candidate bypass tag or lost exclusive traffic." >&2
  exit 3
}

# Reconciliation is the sole scheduled application job. Updating a Cloud Run
# Job is atomic; an overlapping old/new execution is safe because routine
# migrations are forward-compatible and reconciliation operations converge.
gcloud run jobs deploy "$reconcile_job" \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --image "$IMAGE" \
  --service-account "illinicover-web@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "^@^DJANGO_SETTINGS_MODULE=config.settings.production@DEPLOYMENT_ENVIRONMENT=production@DATABASE_MODE=pooled@PUBLIC_API_ORIGIN=${PUBLIC_API_ORIGIN}@CODE_REVISION=${CODE_REVISION}" \
  --set-secrets "ILLINICOVER_SECRETS_JSON=${web_secret}:${web_version}" \
  --command python \
  --args server/manage.py,reconcile_revenuecat,--settings=config.settings.production \
  --cpu 1 --memory 512Mi --task-timeout 20m --max-retries 1 --tasks 1 --quiet
gcloud run jobs describe "$reconcile_job" \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json \
| python3 ops/deployment/verify-cloud-run.py \
    --expected-image "$IMAGE" --expected-revision "$CODE_REVISION" \
    --expected-mode pooled --expected-secret "${web_secret}:${web_version}"
gcloud run jobs add-iam-policy-binding "$reconcile_job" \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
  --member "serviceAccount:${scheduler_identity}" --role roles/run.invoker --quiet
gcloud run jobs get-iam-policy "$reconcile_job" \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format=json \
| python3 -c 'import json,sys
member=sys.argv[1]
bindings=json.load(sys.stdin).get("bindings",[])
valid=any(row.get("role")=="roles/run.invoker" and member in row.get("members",[]) for row in bindings)
raise SystemExit(0 if valid else 1)' "serviceAccount:${scheduler_identity}"

scheduler_uri="https://run.googleapis.com/v2/projects/${GCP_PROJECT_ID}/locations/${GCP_REGION}/jobs/${reconcile_job}:run"
scheduler_args=(
  --project "$GCP_PROJECT_ID" --location "$scheduler_region"
  --schedule '17 10 * * *' --time-zone Etc/UTC
  --uri "$scheduler_uri" --http-method POST --message-body '{}'
  --headers Content-Type=application/json
  --oauth-service-account-email "$scheduler_identity"
  --oauth-token-scope https://www.googleapis.com/auth/cloud-platform
  --max-retry-attempts 3 --min-backoff 30s --max-backoff 10m
  --max-retry-duration 1h --attempt-deadline 30m --quiet
)
if scheduler_state="$(gcloud scheduler jobs describe "$reconcile_job" \
  --project "$GCP_PROJECT_ID" --location "$scheduler_region" \
  --format='value(state)' 2>/dev/null)"; then
  [[ "$scheduler_state" == "ENABLED" || "$scheduler_state" == "PAUSED" ]] || {
    echo "Reconciliation schedule is not in a recoverable state." >&2
    exit 3
  }
  gcloud scheduler jobs update http "$reconcile_job" "${scheduler_args[@]}"
  if [[ "$scheduler_state" == "PAUSED" ]]; then
    gcloud scheduler jobs resume "$reconcile_job" \
      --project "$GCP_PROJECT_ID" --location "$scheduler_region" --quiet
  fi
else
  gcloud scheduler jobs create http "$reconcile_job" "${scheduler_args[@]}"
fi
gcloud scheduler jobs describe "$reconcile_job" \
  --project "$GCP_PROJECT_ID" --location "$scheduler_region" --format=json \
| python3 -c 'import json,sys
item=json.load(sys.stdin)
valid=(item.get("httpTarget",{}).get("uri")==sys.argv[1]
 and item.get("httpTarget",{}).get("oauthToken",{}).get("serviceAccountEmail")==sys.argv[2]
 and item.get("schedule")=="17 10 * * *" and item.get("timeZone")=="Etc/UTC"
 and item.get("state")=="ENABLED")
raise SystemExit(0 if valid else 1)' "$scheduler_uri" "$scheduler_identity"

candidate_started=false
trap - EXIT HUP INT TERM
echo "Deployed ${CODE_REVISION} as ${candidate}; preparation, live, and reconciliation readback passed."
