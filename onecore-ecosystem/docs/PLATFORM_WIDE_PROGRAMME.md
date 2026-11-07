# Platform-wide programme

This is a separate cross-module programme. It is not a feature toggle inside any
single business module. Its control plane is tenant-scoped and all lifecycle
changes are audited.

## Workstreams and implementation contracts

### Security and identity
- MFA/TOTP enrolment, encrypted TOTP secrets, one-time recovery codes, rotation and
  step-up authentication for privileged actions.
- OIDC authorization-code flow with PKCE, issuer/audience/nonce validation,
  state replay prevention, signed metadata/JWKS refresh and explicit account linking.
- Device inventory, session revocation, absolute and idle expiry, password reset and
  email verification with single-use hashed tokens.
- Distributed rate limits and lockout counters must use a shared store (not a
  process-local limiter). Privileged events feed a security event pipeline.
- Penetration testing, dependency scanning, secret scanning, SBOM and vulnerability
  SLAs are release gates, not claims made by an API status field.

### Subscriptions and integrations
- Plans, entitlements, subscriptions, invoices, renewals, grace periods, suspension,
  cancellation, refunds and payment reconciliation require idempotent provider
  event processing and a ledger of provider references.
- Integration credentials are references to a secret manager. Never store raw
  credentials in tenant JSON. Rotation must support overlap and rollback.
- Webhook delivery requires durable leases, bounded exponential backoff, signatures,
  replay protection, idempotency and a dead-letter queue with operator replay.
- Production status requires provider sandbox evidence and a human-approved
  certification record. A configuration record alone is not certification.

### CMS and onboarding
- Content authoring, review, approval, scheduled publication, version history,
  rollback and tenant audience controls.
- Tenant onboarding tracks organization, branch, users, roles, data import,
  module activation and training milestones independently.
- Imports require preview, field mapping, validation report, idempotent batches,
  dry-run and rollback/reconciliation strategy.

### Business intelligence
- Governed metric definitions, tenant/branch scope, row-level authorization,
  dashboard and report versions, scheduled exports and audit history.
- Warehouse ingestion uses incremental checkpoints, late-arriving data handling,
  retention policy and reconciliation against operational source totals.
- PII minimization, export authorization and download expiry apply to every report.

### Operations and resilience
- Structured logs, request/trace correlation, metrics, SLOs, alert routing and
  background job queue health.
- Encrypted backups, tested point-in-time recovery, RPO/RTO targets, restore drills,
  high availability, deployment rollback and expand/contract database migrations.
- Load, fault-injection, security and full production UAT are required before release.

## Initial control-plane API

Base path: `/api/v1/platform/programme`

- `GET /domains` lists the governed resource families.
- `POST /{domain}/{kind}` creates a tenant-owned draft resource.
- `GET /{domain}/{kind}` lists resources in the active tenant only.
- `POST /{domain}/{kind}/{id}/transition` applies an explicit lifecycle transition.
- `POST /webhooks/{kind}/enqueue` creates an idempotency-keyed delivery record.
- `GET /webhooks/deliveries` lists delivery metadata without exposing payloads.

Every route requires an authenticated active tenant membership and the relevant
permission. Lifecycle transitions are validated and audited. This control plane is
a foundation; it does not itself provide external identity, payment, email, SMS,
secret-manager, queue-worker, warehouse, object-storage or infrastructure services.

## Release gates still required

Do not claim production readiness until dedicated implementation and acceptance
tests exist for each external integration and operational control. In particular,
MFA/OIDC flows, email delivery, payment provider certification, durable distributed
webhook workers, warehouse pipelines, centralized telemetry, backup/PITR, HA,
restore drills, pen tests, load tests and production UAT must be completed against
the actual deployment environment.
