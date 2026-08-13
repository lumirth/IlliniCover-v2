# Neon database role and TLS receipt — 2026-08-12

This is a read-only production receipt captured at `2026-08-12T17:59Z` from
the existing Google Secret Manager bundles in project `illinicover`. The audit
did not change Neon, Google Cloud, roles, grants, passwords, or secret
versions. Commands decoded credentials only in process memory and emitted no
database URL, hostname, password, or secret value.

## Credential routing and transport

The enabled `illinicover-web`, `illinicover-migrate`, and `illinicover-jobs`
secret versions were each read with:

```bash
gcloud secrets versions access latest --secret SECRET --project illinicover
```

The enabled-version readback was web version 3, migrate version 2, and jobs
version 3 (created at `2026-08-12T15:17:34Z`, `15:17:34Z`, and `15:17:35Z`
respectively); each secret had exactly one enabled version.

A redacting Python wrapper selected only `DATABASE_URL` or
`DATABASE_URL_DIRECT`, parsed non-secret connection metadata, and connected
with psycopg 3.3.4 and libpq 18.4. The observed split is:

| Workload bundle | Secret key | Endpoint | PostgreSQL login |
| --- | --- | --- | --- |
| web | `DATABASE_URL` | pooled | `illinicover_runtime` |
| migrate | `DATABASE_URL_DIRECT` | direct | `illinicover_schema` |
| jobs (receipt-time bundle) | `DATABASE_URL_DIRECT` | direct | `illinicover_runtime` |

This receipt predates the pooled normal-job rollout. Current repository
configuration routes bootstrap, refresh, and nightly through the pooled
`DATABASE_URL` in the jobs bundle; migration remains direct.

All three stored URLs explicitly set `sslmode=require` and
`channel_binding=require`. For every bundle, psycopg reported
`connection.pgconn.ssl_in_use = true`. Independent `psql -X -c '\conninfo'`
readback reported TLS 1.3, OpenSSL, 256-bit `TLS_AES_256_GCM_SHA384`, no TLS
compression, PostgreSQL ALPN, and `Superuser: off` for every client leg.
Connections also succeeded when the audit strengthened the client parameters
to `sslmode=verify-full`, `channel_binding=require`, and the explicit macOS CA
bundle `/etc/ssl/cert.pem`. This verifies hostname and chain validation is
available, but the deployed URLs currently request encryption and SCRAM
channel binding without requesting `verify-full`; see gaps below.

The following is the reusable shape of the redacted transport check. `DSN` was
obtained in memory from the relevant JSON key and was never printed:

```python
with psycopg.connect(DSN, connect_timeout=10) as connection:
    assert connection.pgconn.ssl_in_use

with psycopg.connect(
    DSN,
    sslmode="verify-full",
    sslrootcert="/etc/ssl/cert.pem",
    channel_binding="require",
    connect_timeout=10,
) as connection:
    assert connection.pgconn.ssl_in_use
```

## Role attributes and separation

Catalog queries ran through the migration credential against PostgreSQL 18.4.
The application and migration identities are separate login roles. The support
capability exists as a separate `NOLOGIN` group role:

| Role | Login | Inherit | Superuser | Create role | Create DB | Replication | Bypass RLS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `illinicover_runtime` | yes | no | no | no | no | no | no |
| `illinicover_schema` | yes | no | no | no | no | no | no |
| `illinicover_readonly` | no | no | no | no | no | no | no |

`pg_auth_members` returned zero memberships involving any `illinicover_*`
role. Pairwise `pg_has_role(..., 'USAGE')` and `pg_has_role(..., 'SET')` checks
were false, so runtime cannot inherit or switch to schema/support, schema cannot
inherit or switch to runtime/support, and the read-only group cannot switch to
either login role. There is therefore no configured support login or group
member at receipt time.

The database is owned by `illinicover_schema`. The `public` schema is owned by
`pg_database_owner`, which resolves to that database owner. All 57 application
tables and 30 sequences are owned by `illinicover_schema`.

The catalog commands were structurally equivalent to:

```sql
SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb,
       rolcanlogin, rolreplication, rolbypassrls
FROM pg_roles
WHERE rolname LIKE 'illinicover%';

SELECT member.rolname, parent.rolname, admin_option,
       inherit_option, set_option
FROM pg_auth_members
JOIN pg_roles member ON member.oid = pg_auth_members.member
JOIN pg_roles parent ON parent.oid = pg_auth_members.roleid
WHERE member.rolname LIKE 'illinicover%'
   OR parent.rolname LIKE 'illinicover%';
```

## Effective privileges

Effective privileges were counted with `has_database_privilege`,
`has_schema_privilege`, `has_table_privilege`, and
`has_sequence_privilege` across every current object in `public`:

| Capability | Runtime | Schema | Read-only support role |
| --- | ---: | ---: | ---: |
| Database CONNECT | yes | yes | yes |
| Database CREATE | no | yes | no |
| Database TEMPORARY | yes | yes | no |
| Schema USAGE | yes | yes | yes |
| Schema CREATE | no | yes | no |
| SELECT tables | 57/57 | 57/57 | 57/57 |
| INSERT/UPDATE/DELETE tables | 57/57 | 57/57 | 0/57 |
| TRUNCATE tables | 0/57 | 57/57 | 0/57 |
| REFERENCES/TRIGGER/MAINTAIN tables | 0/57 | 57/57 | 0/57 |
| Sequence USAGE/SELECT/UPDATE | 30/30 | 30/30 | 0/30 |

No listed table privilege is grantable by runtime or read-only support. Runtime
has the CRUD and sequence access needed by the web and scheduled jobs,
but cannot create schema objects, truncate tables, add triggers, declare
references, maintain tables, or assume the schema owner. The support group can
connect and select all tables but cannot mutate tables, sequences, schema, or
database. There are no RLS-enabled tables; the trust boundary is the server and
these database grants, not client-side row policies.

Default ACLs owned by `illinicover_schema` preserve the split for future
objects in `public`: new tables grant runtime SELECT/INSERT/UPDATE/DELETE and
read-only support SELECT; new sequences grant runtime USAGE/SELECT/UPDATE.
Neither grantee receives grant option. The database and schema ACLs expose no
`PUBLIC` database privilege or schema CREATE; PostgreSQL retains public schema
USAGE only.

## Production transport hardening follow-up

At `2026-08-12T18:11Z`, after this read-only receipt identified the hostname
verification gap, the three Secret Manager bundles were rotated in place. All
current database URLs now require:

```text
sslmode=verify-full
sslrootcert=/etc/ssl/certs/ca-certificates.crt
channel_binding=require
```

The CA path is the Debian system trust bundle present in the digest-pinned
production base image. A follow-up Django production-settings connection test
used each latest secret version and proved the web pooled login, migration
direct login, and receipt-time jobs direct login all authenticated as their expected roles
with libpq TLS active and the exact three fail-closed options above. No URL,
hostname, password, or secret value was emitted. The prior `sslmode=require`
versions were temporarily retained as rollback material at this receipt
boundary. They were later disabled and destroyed as recorded in
`2026-08-12-gcp-release-preflight.md`; this historical paragraph is not current
Secret Manager inventory.

## Honest gaps and release implications

- A support capability is provisioned, but it is a `NOLOGIN` group with no
  member. There is no support credential in the three GCP workload bundles.
  This is least privilege and prevents ambient support access, but a live
  support-session authentication test is not possible until an explicitly
  authorized, time-bounded login is added as a member.
- The stored URLs now require hostname/CA verification as described above.
  The remaining transport proof is the final Cloud Run migration/bootstrap/web
  run using those latest versions; this receipt does not substitute for that
  runtime acceptance.
- `pg_stat_ssl` reported `ssl = false` through Neon's SQL-visible backend even
  while libpq and `psql \conninfo` reported TLS in use. This is consistent with
  observing a TLS-terminating Neon proxy/client leg rather than the external
  connection at the compute backend. The receipt therefore treats the client
  libpq state and `\conninfo` as authority for client-to-Neon transport; it
  makes no claim about Neon's internal proxy-to-compute hop.
- The web pooler, direct migration endpoint, and receipt-time direct jobs endpoint were
  checked from this macOS operator host. A successful Cloud Run execution proves
  the credential and query path from Cloud Run but does not by itself expose
  libpq TLS negotiation details. A post-deploy, secret-safe runtime transport
  diagnostic would be stronger evidence if one is deliberately implemented.

This receipt does not prove the subsequently selected jobs pooler URL; final
Cloud Run readback must confirm `DATABASE_MODE=pooled` for normal jobs. At this
receipt boundary the role split is materially least-privilege and
future-object-safe, and the latest deployed-secret values require encryption,
hostname/CA verification, and SCRAM channel binding.
