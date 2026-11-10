# Runtime database role provisioning

Production API and worker processes must set `ONECORE_DATABASE_RUNTIME_ROLE`
to a pre-provisioned PostgreSQL role (recommended: `onecore_api`). The database
login user configured in `SUPABASE_DB_URL` must be granted membership in this
role. The role must be `NOSUPERUSER NOBYPASSRLS`, have only the required
schema/table/sequence/function grants, and must not own tenant tables.

The application executes `SET LOCAL ROLE` at the start of every SQLAlchemy
transaction, verifies the effective role and rejects superuser/BYPASSRLS roles.
Because the role switch is transaction-local, pooled connections revert on
commit/rollback. Keep migration execution on a separate owner credential and
never grant the runtime role ownership or BYPASSRLS. Do not use Supabase's
`service_role` or `postgres` credential as the application runtime identity.

Example provisioning (run once as a database administrator, after reviewing
the exact privileges required by the deployed migration head):

```sql
CREATE ROLE onecore_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT onecore_api TO onecore_runtime_login;
```

The login role, schema privileges, table privileges, sequence privileges and
function EXECUTE grants must be provisioned by the deployment operator for the
actual Supabase project. This repository does not contain database credentials
and cannot provision a remote Supabase role by itself.


## PostgreSQL RLS behavior verification in CI

The repository CI job applies the full Alembic migration chain to an ephemeral
PostgreSQL 16 database, then creates a CI-only `onecore_ci_runtime` role with
`NOLOGIN`, `NOSUPERUSER` and `NOBYPASSRLS`. The role receives only the table,
sequence and helper-function grants needed by the focused behavior test; it is
not a production credential and is discarded with the CI database.

`tests/test_postgres_tenant_rls_behavior.py` exercises the production
`apply_runtime_database_role` transaction-local switch and verifies that a
user with membership in tenant A cannot read or write tenant B records or
memberships, cannot read tenant B audit events, and cannot update or delete
append-only audit rows. The separate catalog test continues to check forced RLS
coverage for every public table carrying `organization_id`.

This CI evidence tests PostgreSQL policy behavior, but it is not a production
Supabase role rehearsal. Operators must still provision the actual login/runtime
roles with reviewed grants, run the checks against the target Supabase project,
and verify provider-specific worker roles and callback contexts before release.
