# Secret rotation

1. Create the replacement at the owning provider without revoking the old
   value yet.
2. Build the appropriate JSON bundle or individual preview secret in a local
   mode-0600 temporary file. Never place the value in shell history, workflow
   logs, screenshots, or an issue.
3. Run the metadata-only inventory guard. Both `ENABLED` and `DISABLED` count
   as billable active versions. Reconcile any disabled or duplicate candidate
   left by an interrupted rotation before adding another version.
4. Add one new Google Secret Manager version to the exact
   environment/identity secret. Production web, migration, and jobs are
   separate bundles; preview uses separate entries. Rotate one bundle at a
   time when the six-version free allowance is already occupied.
5. Deploy the normal immutable revision. The workflow resolves `latest` once,
   pins that numeric version in every owning Cloud Run resource, and reads the
   exact reference back with release-correlated health.
6. After the release is accepted, the workflow disables each superseded
   version, verifies the `DISABLED` state, destroys it, and verifies
   `DESTROYED`. It then requires at most six active versions and no disabled
   versions. Only then revoke the superseded provider credential.

Do not preserve a chain of disabled versions as rollback material: disabled
versions still cost money and an old provider credential may already be
revoked. A rollback across a secret rotation creates a fresh version containing
the accepted current credential and redeploys the known-good image against
that numeric version. Ordinary application rollback remains a traffic change
only when its revision's pinned versions still exist.

If the secret is suspected exposed, rotate immediately and inspect redacted
application/provider audit logs. Never grant a web runtime the migration bundle
to make rotation easier. A successful health check proves only the runtime
seam; RevenueCat and SMTP rotations need their own sandbox/test delivery.
