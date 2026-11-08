# OneCore Technologies Ltd — Ecosystem Starter

**One Platform. Every Organization. Anywhere.**  
This repository is a runnable, modular-monolith foundation generated from the supplied *OneCore Complete Ecosystem & Workflow Master Specification* (5 November 2026, including the domain/branding/maintenance addendum).

It provides the shared platform foundation, a tenant-aware generic module API, integration adapter contracts, a public landing page, operational endpoints, Docker setup, tests, and the complete 75-category scope catalogue. It is deliberately structured so provider-specific credentials and URLs are configured through environment variables and adapter implementations.

> **Important delivery boundary:** this is an executable foundation and module scaffold, not a claim that all 75 enterprise domains are already production-complete, legally certified, or connected to providers. The specification itself says each feature must pass database, backend, frontend, permissions, validation, tests, monitoring, documentation and deployment checks before being marked complete. Domain workflows that need specialist rules (clinical, financial, tax, payroll, education, etc.) require implementation and UAT before production use.

## Stack
- Python 3.12, FastAPI, SQLAlchemy 2, Pydantic settings
- Supabase-managed PostgreSQL as the production system of record; SQLite for local development and tests\n- SQLAlchemy + psycopg 3 connects directly to Supabase Postgres; Alembic migrations and background workers use the same connection\n- Supabase credentials remain server-side; the React frontend accesses data only through authenticated OneCore APIs
- JWT access tokens, Argon2 password hashing, tenant-aware authorization
- Adapter interfaces for M-Pesa, KRA eTIMS, SHA/DHA AfyaLink, banks, messaging, AI and object storage
- Docker Compose, pytest, OpenAPI

## Quick start
```bash
cp .env.example .env
docker compose up --build
```
API: http://localhost:8000  
Interactive API docs: http://localhost:8000/docs  
Health: http://localhost:8000/health  
Public site: http://localhost:8000/  
CRM automation: http://localhost:8000/crm/automation  
Healthcare privacy: http://localhost:8000/healthcare

For local non-Docker development:
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## First-run bootstrap
Set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` in `.env` before first startup. The bootstrap account is a platform administrator for development. Replace it with a controlled production provisioning process, enforce MFA, and rotate the password before any real deployment.

## Developer integration rule
1. Implement or select a provider adapter in `app/integrations/`.
2. Put only secrets and environment-specific values in `.env` / deployment secret manager.
3. Set `INTEGRATION_<PROVIDER>_ENABLED=true` and the relevant provider variables.
4. Test callbacks, signature validation, retries, idempotency and reconciliation in sandbox.
5. Enable production only after provider onboarding, legal/contractual approval and acceptance tests.

The application starts with adapters disabled. No real payment, tax, health, messaging, AI or bank call is made by default. Never paste production secrets into source control.

## Main API groups
- `/api/v1/auth` — login and current identity
- `/api/v1/organizations` — organizations and membership
- `/api/v1/modules` — 75-category catalogue and enabled modules
- `/api/v1/records/{module_key}` — tenant-scoped generic records (starter data plane)
- `/api/v1/integrations` — provider status/configuration metadata (never returns secrets)
- `/api/v1/ai` — tenant-scoped OneCore AI chat, document analysis, conversations and usage
- `/api/v1/operations` — audit events and operational overview
- `/health` — liveness/readiness information

## CRM campaign automation and healthcare privacy

- CRM includes versioned email/SMS/WhatsApp templates, nested AND/OR audience segmentation, one-time/daily/weekly campaign schedules, personalized per-recipient snapshots, consent revalidation and retry-safe worker execution.
- Docker Compose starts a dedicated `crm-scheduler` worker sharing the API database. For non-Docker deployments run `python -m app.workers.crm_scheduler` from `onecore-ecosystem`. Run one worker with SQLite; use PostgreSQL for multiple workers.
- Healthcare adds branch-scoped healthcare roles, patient-level read/write grants, expiry/revocation, append-only consent history, 15-minute justified break-glass access, appointments, encrypted patient profiles/clinical notes and an audited access trail.
- Set `HEALTHCARE_PHI_ENCRYPTION_KEY` to a dedicated Fernet key before registering patient data. See `docs/HEALTHCARE_PRIVACY.md` and `docs/CRM_AUTOMATION.md`.
- These are technical controls, not regulatory certification. MFA/step-up, managed key rotation, retention/data-subject workflows, penetration testing, clinical/legal governance and live provider UAT remain production requirements.

## Architecture and extension points
See `docs/ARCHITECTURE.md`, `docs/INTEGRATIONS.md`, `docs/SECURITY.md`, `docs/MODULE_DELIVERY.md`, `docs/ONECORE_AI.md`, and `docs/SPEC_TRACEABILITY.md`.

## Production checklist (minimum)
- Configure PostgreSQL, Redis/queue, object storage, TLS, reverse proxy and managed secrets.
- Replace development bootstrap with invitation/provisioning; add MFA/SSO and privileged-session controls.
- Add migrations (Alembic), backup/PITR and tested restore; define RTO/RPO.
- Complete tenant/branch authorization tests and independent security review.
- Implement specialist domain schemas and workflows for each enabled product.
- Complete provider sandbox/UAT/certification and reconciliation.
- Add observability, alerting, rate limits, WAF, malware scanning and retention policies.
- Complete Kenya Data Protection Act/GDPR applicability assessment and contracts.
- Do not advertise SHA/eTIMS certification or production connectivity until formally approved and tested.
