# Security, Privacy and Compliance

Master specification category: **32**

## Source scope
Tenant isolation; RBAC/MFA; password/session security; encryption; API auth/rate limits; brute-force/CSRF/XSS/SQLi protections; secure uploads; device/session revocation; audit; retention/export/deletion/consent; encrypted backups; vulnerability/dependency scans; penetration tests; incidents/alerts; Kenya Data Protection Act and GDPR where applicable; enhanced health/finance controls.

## Implementation status
Scaffold only. This folder reserves the domain boundary; it is not a claim of production implementation.

## Required implementation
- Define domain entities, constraints, indexes and migrations.
- Add domain services and versioned API routes.
- Enforce tenant, branch and role authorization at the service layer.
- Add validation, approval workflows, audit events and idempotency where needed.
- Build responsive user/admin workflows and accessible states.
- Add unit, integration, security and end-to-end tests.
- Add monitoring, retention, backup/restore and operational documentation.
- Complete sandbox/UAT and release approval for external dependencies.
