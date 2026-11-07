# Service Directory and Integration Registry

Master specification category: **67**

## Source scope
admin.onecore.co.ke/services: service ID/owner/description/category/dependencies/endpoints/version/environment/availability/access/maintenance/configuration/usage/integration health/deprecation/retirement/docs/audit.

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
