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
