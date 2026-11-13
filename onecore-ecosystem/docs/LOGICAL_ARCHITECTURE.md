# Logical backend architecture and repository boundary

## Decision: preserve the current API deployment

The FastAPI backend remains physically in this repository at `onecore-ecosystem/`. It is the logical `apps/api` application in the proposed OneCore architecture, but must not be moved into a new monorepo path at this stage.

- Render builds this backend using the existing root `render.yaml`, `onecore-ecosystem/Dockerfile` and Docker context.
- Supabase PostgreSQL is the production system of record.
- The Lovable/TanStack frontend remains in the separate `onecore-digital-hub` repository and is deployed independently.
- The frontend calls the API over HTTPS through its configured API origin and the established `/api/v1` prefix.

Do not create a second API service or move/duplicate the backend as part of logical alignment.

## Logical mapping to the proposed tree

| Proposed monorepo area | Current physical location | Responsibility |
| --- | --- | --- |
| `apps/api/app/main.py` | `onecore-ecosystem/app/main.py` | FastAPI application entry point |
| `apps/api/app/core/` | `onecore-ecosystem/app/` core/configuration modules | Settings, shared runtime and platform primitives |
| `apps/api/app/middleware/` | `onecore-ecosystem/app/` middleware modules | Request context, CORS and security middleware |
| `apps/api/app/security/` | `onecore-ecosystem/app/` authentication/authorization modules | Authentication, permissions and tenant enforcement |
| `apps/api/app/api/v1/` | `onecore-ecosystem/app/` API routers | Versioned HTTP endpoints |
| `apps/api/app/modules/` | `onecore-ecosystem/app/` domain modules | Business-domain services and schemas |
| `apps/api/app/integrations/` | `onecore-ecosystem/app/integrations/` | Provider adapters and callbacks |
| `apps/api/app/database/` | `onecore-ecosystem/app/` database modules | SQLAlchemy engine, sessions and persistence |
| `apps/api/app/jobs/` and `workers/` | `onecore-ecosystem/app/` worker modules | Scheduled and asynchronous work |
| `apps/api/migrations/` | Backend Alembic migration directory | Authoritative schema history |
| `apps/api/tests/` | `onecore-ecosystem/tests/` | API, domain, security and integration tests |
| `apps/api/requirements.txt` | `onecore-ecosystem/requirements.txt` | Python dependencies |
| `apps/api/Dockerfile` | `onecore-ecosystem/Dockerfile` | Render container build |

The table describes logical ownership; it does not claim that every proposed package/directory or every domain workflow already exists or is complete.

## Domain ownership

The backend is the source of truth for authentication, tenant and organization membership, user/role permissions, business rules, data validation, financial posting, inventory movements, procurement approvals, POS transactions, payroll calculations, audit records and database persistence.

Logical domain boundaries should be maintained for authentication, tenants, users, billing, subscriptions, invoices, payments, finance, accounting, HR, payroll, CRM, inventory, POS, procurement, documents, reports, developer API, support and superadmin. Provider-specific code belongs under integrations (for example M-Pesa, eTIMS, SHA, email and notifications).

Do not claim a domain is production-complete solely because a generic record endpoint, catalogue entry, adapter interface or UI screen exists. Specialist workflows require domain-specific schemas, authorization, transactional behavior, idempotency where appropriate, auditability, tests and user acceptance.

## Database and security boundaries

- This repository owns SQLAlchemy models and Alembic migrations for the API.
- Supabase is managed PostgreSQL; credentials remain server-side in Render secrets.
- Do not expose database URLs, service-role keys, JWT signing secrets or provider credentials to the frontend.
- Tenant and branch scope must be derived and checked server-side for every protected read and write. A client-supplied organization identifier is not proof of access.
- Superadmin APIs require dedicated server-side privileged authorization, MFA/step-up controls where configured, and audit logging. A hidden frontend route is not a security boundary.
- Provider integrations remain disabled until credentials, callback validation, sandbox/UAT and reconciliation tests are complete.

## Frontend contract

The frontend repository is `kiiplangatemanuel-bit/onecore-digital-hub`. It calls the API through `VITE_ONECORE_API_URL` plus `/api/v1`. The frontend variable contains only the public HTTPS API origin; never put secrets in it.

Before a frontend module is marked connected, verify:
1. Actual backend route and HTTP method.
2. Request and response schema.
3. Authentication/session behavior.
4. Tenant, branch and role/permission enforcement.
5. Real database persistence and transaction behavior.
6. Validation, error semantics and audit requirements.
7. Automated API/contract tests and frontend integration tests.

Unavailable endpoints must be represented as unavailable/not connected in the UI, not simulated with seeded demo data.

## Render and Supabase deployment continuity

Keep the existing Render Blueprint and Docker build paths unchanged during logical alignment. Preserve the `/ready` health check and the migration-before-server startup behavior. Any future change to Docker context, environment variable names, health checks or database connection settings requires a reviewed deployment change and a tested rollback.

## Gate before a physical monorepo move

A future move into `apps/api` must be a separate migration project and is blocked until:
- The frontend/Lovable and Vercel move has passed an isolated branch and preview test.
- Render's new repository connection, Docker context, Blueprint, secrets and health check have passed staging deployment.
- Alembic history and Supabase schema ownership remain singular, with backup and restore verified.
- CI covers backend, frontend, contracts, tenant isolation and security in the new workspace.
- Production smoke tests pass and rollback is proven.

Until every gate passes, this repository remains the deployed backend and the logical architecture mapping is authoritative.
