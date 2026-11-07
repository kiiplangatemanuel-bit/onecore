# Architecture

## Five pillars
1. Core Platform — identity/SSO, tenant isolation, RBAC, configuration, billing, flags, notifications, search, automation and audit.
2. Products — Business OS, AI, Cloud, Connect and industry systems.
3. Digital Ecosystem — public website, CMS, customer app, developer/docs/support/partner/community/careers/trust/status/files/events portals.
4. Operations Centre — superadmin, onboarding, maintenance, incidents, releases, service registry, monitoring, backups and support.
5. Enterprise Governance — security, privacy, compliance, records, approvals, audit, data governance, continuity and disaster recovery.

## Architectural decision
Start as a modular monolith with explicit domain boundaries. Do not split the 75 scope categories into 75 microservices. Extract services only when scale, security or operational needs justify it.

## Domain boundaries
`core` owns identity, tenant, membership, permissions and audit. `modules` owns the feature catalogue and domain packages. `integrations` owns provider adapters. `api` exposes versioned contracts. Each domain module should own its schemas, services, validation, permissions, tests and events.

## Data isolation
Every organization-owned record carries `organization_id`. Every tenant request uses `X-Organization-ID` and verifies active membership before reading/writing records. Add branch-level authorization to every domain route before enabling branch-sensitive features. Never rely on frontend filtering.
