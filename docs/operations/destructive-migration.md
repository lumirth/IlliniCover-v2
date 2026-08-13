# Exceptional destructive migration

This path applies only when `scripts/ci/classify_migrations.py` finds a removed
migration file or an operation that may reinterpret, remove, or make stored
data incompatible. Redesign the change as expand → use → later contract first.
Ordinary additive migrations continue through normal CI and automatic deploy.

For a remaining exception:

1. Add the `preview` label and wait for `Shared preview` to migrate, seed,
   deploy, and deep-probe the exact pull-request head SHA successfully.
2. Perform or confirm a current Neon point-in-time restore/snapshot check for
   the pre-change production state. Put its non-secret HTTPS audit/receipt link
   in the pull request body on an exact line:

   ```text
   Destructive migration restore receipt: https://...
   ```

3. Add the single `destructive-migration-reviewed` label only after both
   receipts exist. Rerun `CI / Required` after the preview completes. The
   selected backend check binds the label, restore link, preview pull-request
   number, and preview run to the exact head SHA; a cleanup-only preview run
   does not count.
4. Merge only after the stable required check passes. The production workflow
   independently reclassifies migrations between the previous and new `main`
   revisions, resolves the associated merged pull request, and verifies the
   same label, restore receipt, and successful exact-SHA preview before WIF,
   image build, migration, or Cloud Run mutation.

A direct push, missing/ambiguous pull request, different preview SHA, HTTP or
missing restore link, deleted migration, or failed/cleanup-only preview stops
the release. Do not bypass the gate by editing workflow variables. Production
still migrates before web traffic and never automatically reverses a database
migration during application rollback. Use `restore-database.md` only if data
recovery is actually required.
