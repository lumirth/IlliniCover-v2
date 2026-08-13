from __future__ import annotations

import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2] / "ops" / "deployment" / "deploy-cloud-run.sh"
).read_text()


def position(fragment: str, *, after: int = 0) -> int:
    location = SCRIPT.find(fragment, after)
    if location < 0:
        raise AssertionError(f"deployment script is missing {fragment!r}")
    return location


class SchedulerCutoverOrderTests(unittest.TestCase):
    def test_scheduler_is_guarded_before_any_job_image_swap(self) -> None:
        discovery = position('SCHEDULER_PREVIOUS_STATE="$(')
        guard = position("SCHEDULER_RELEASE_GUARD_ACTIVE=true", after=discovery)
        paused = position("--state PAUSED", after=guard)
        first_job_deploy = position("gcloud run jobs deploy illinicover-migrate")

        self.assertLess(discovery, guard)
        self.assertLess(guard, paused)
        self.assertLess(paused, first_job_deploy)

    def test_target_stays_paused_through_migration_and_web_probes(self) -> None:
        scheduler_update = position('gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME"')
        paused_target = position("--state PAUSED", after=scheduler_update)
        migration = position("gcloud run jobs execute illinicover-migrate")
        optional_bootstrap = position("gcloud run jobs execute illinicover-bootstrap")
        web_deploy = position('gcloud run deploy "$SERVICE_NAME"')
        web_probe = position('probe_origin "$SERVICE_URL"')
        resume = position('gcloud scheduler jobs resume "$SCHEDULER_JOB_NAME"')

        self.assertLess(scheduler_update, paused_target)
        self.assertLess(paused_target, migration)
        self.assertLess(migration, optional_bootstrap)
        self.assertLess(optional_bootstrap, web_deploy)
        self.assertLess(web_deploy, web_probe)
        self.assertLess(web_probe, resume)

    def test_guard_is_disarmed_only_after_final_state_verification(self) -> None:
        resume = position('gcloud scheduler jobs resume "$SCHEDULER_JOB_NAME"')
        enabled = position("--state ENABLED", after=resume)
        preserved_paused = position("--state PAUSED", after=enabled)
        disarmed = position("SCHEDULER_RELEASE_GUARD_ACTIVE=false", after=preserved_paused)

        self.assertLess(resume, enabled)
        self.assertLess(enabled, preserved_paused)
        self.assertLess(preserved_paused, disarmed)

    def test_exit_trap_attempts_to_restore_paused_state(self) -> None:
        handler = position("scheduler_pause_on_exit()")
        pause = position('gcloud scheduler jobs pause "$SCHEDULER_JOB_NAME"', after=handler)
        trap = position("trap scheduler_pause_on_exit EXIT", after=pause)

        self.assertLess(handler, pause)
        self.assertLess(pause, trap)

    def test_failed_enabled_schedule_persists_resume_intent_for_the_next_release(self) -> None:
        self.assertIn('SCHEDULER_RESUME_MARKER="illinicover-release-guard:resume"', SCRIPT)
        self.assertIn('scheduler_current_description()', SCRIPT)
        self.assertIn('SCHEDULER_PREVIOUS_DESCRIPTION="$(' , SCRIPT)
        self.assertIn(
            '"$SCHEDULER_PREVIOUS_DESCRIPTION" == "$SCHEDULER_RESUME_MARKER"',
            SCRIPT,
        )
        self.assertIn('--description "$SCHEDULER_RELEASE_DESCRIPTION"', SCRIPT)

    def test_resume_intent_is_read_back_before_the_pause_guard_is_armed(self) -> None:
        discovery = position('SCHEDULER_PREVIOUS_STATE="$(')
        snapshot = position("snapshot_release_resources", after=discovery)
        persist = position(
            'gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME"',
            after=snapshot,
        )
        readback = position(
            '"$(scheduler_current_description)" != "$SCHEDULER_RESUME_MARKER"',
            after=persist,
        )
        guard = position("SCHEDULER_RELEASE_GUARD_ACTIVE=true", after=readback)
        pause = position(
            'gcloud scheduler jobs pause "$SCHEDULER_JOB_NAME"',
            after=guard,
        )

        self.assertLess(snapshot, persist)
        self.assertLess(persist, readback)
        self.assertLess(readback, guard)
        self.assertLess(guard, pause)

    def test_private_candidate_uses_the_base_service_as_its_token_audience(self) -> None:
        self.assertIn('probe_authenticated_origin "$CANDIDATE_URL" "$SERVICE_URL"', SCRIPT)
        self.assertIn(
            'identity_token="$(gcloud auth print-identity-token --audiences="$audience")"',
            SCRIPT,
        )
        self.assertNotIn('print-identity-token --audiences="$origin"', SCRIPT)

    def test_first_release_stays_fail_closed_through_public_probes(self) -> None:
        armed = position("SERVICE_PUBLIC_ACCESS_PENDING=true")
        grant = position('gcloud run services add-iam-policy-binding "$SERVICE_NAME"', after=armed)
        public_probe = position('probe_origin "$SERVICE_URL"', after=grant)
        disarmed = position("SERVICE_PUBLIC_ACCESS_PENDING=false", after=public_probe)
        trap_cleanup = position(
            'gcloud run services remove-iam-policy-binding "$SERVICE_NAME"'
        )

        self.assertLess(trap_cleanup, armed)
        self.assertLess(armed, grant)
        self.assertLess(grant, public_probe)
        self.assertLess(public_probe, disarmed)


class ArtifactCostGuardTests(unittest.TestCase):
    def test_budgeted_ceiling_allows_one_observed_build(self) -> None:
        self.assertIn("ARTIFACT_BUDGET_BYTES=1000000000", SCRIPT)
        self.assertNotIn("ARTIFACT_FREE_BYTES", SCRIPT)

    def test_reserve_covers_the_observed_image_and_attestation_envelope(self) -> None:
        self.assertIn("NEW_IMAGE_RESERVE_BYTES=268435456", SCRIPT)
        self.assertNotIn("167772160", SCRIPT)
        self.assertNotIn("160 MiB", SCRIPT)

    def test_manual_build_requires_headroom_before_cloud_build(self) -> None:
        headroom = position(
            "REPOSITORY_SIZE_BYTES > ARTIFACT_BUDGET_BYTES - NEW_IMAGE_RESERVE_BYTES"
        )
        build = position("gcloud builds submit", after=headroom)
        first_runtime_mutation = position("gcloud run jobs deploy illinicover-migrate")

        self.assertLess(headroom, build)
        self.assertLess(build, first_runtime_mutation)

    def test_rejected_new_image_is_deleted_before_any_runtime_mutation(self) -> None:
        built = position("IMAGE_BUILT_THIS_RELEASE=true")
        post_build_size = position('REPOSITORY_SIZE_BYTES_AFTER="$(')
        cleanup = position('delete_unserved_release_build "$IMAGE"', after=post_build_size)
        first_runtime_mutation = position("gcloud run jobs deploy illinicover-migrate")

        self.assertLess(built, post_build_size)
        self.assertLess(post_build_size, cleanup)
        self.assertLess(cleanup, first_runtime_mutation)

    def test_failed_release_restores_resources_before_deleting_a_workflow_build(self) -> None:
        handler = position("scheduler_pause_on_exit()")
        restore = position("restore_release_resources_on_failure", after=handler)
        cleanup = position('delete_unserved_release_build "${IMAGE:-}"', after=restore)
        handler_exit = position('exit "$exit_status"', after=cleanup)

        self.assertIn('RELEASE_IMAGE_BUILT="${RELEASE_IMAGE_BUILT:-false}"', SCRIPT)
        self.assertLess(handler, restore)
        self.assertLess(restore, cleanup)
        self.assertLess(cleanup, handler_exit)

    def test_image_cleanup_uses_the_attachment_aware_release_helper(self) -> None:
        self.assertIn("scripts/release/artifact_image_cleanup.py", SCRIPT)
        self.assertNotIn("gcloud artifacts docker images delete", SCRIPT)

    def test_runtime_snapshots_precede_every_release_image_attachment(self) -> None:
        snapshots = position("\nsnapshot_release_resources\n")
        first_job_mark = position("mark_release_job_mutation illinicover-migrate", after=snapshots)
        first_job_deploy = position(
            "gcloud run jobs deploy illinicover-migrate", after=first_job_mark
        )
        service_mark = position("SERVICE_MUTATION_STARTED=true", after=first_job_deploy)
        service_deploy = position('gcloud run deploy "$SERVICE_NAME"', after=service_mark)

        self.assertLess(snapshots, first_job_mark)
        self.assertLess(first_job_mark, first_job_deploy)
        self.assertLess(first_job_deploy, service_mark)
        self.assertLess(service_mark, service_deploy)

    def test_failed_release_restores_the_complete_prior_job_configuration(self) -> None:
        self.assertIn('--job-replace-manifest', SCRIPT)
        self.assertIn('--job-config', SCRIPT)
        self.assertIn('gcloud run jobs replace', SCRIPT)
        self.assertNotIn('gcloud run jobs update "$job"', SCRIPT)


class ReleaseEnvironmentReadbackTests(unittest.TestCase):
    def test_jobs_and_web_verify_the_exact_deployment_environment(self) -> None:
        self.assertGreaterEqual(
            SCRIPT.count('--expected-env "DEPLOYMENT_ENVIRONMENT=production"'),
            2,
        )


if __name__ == "__main__":
    unittest.main()
