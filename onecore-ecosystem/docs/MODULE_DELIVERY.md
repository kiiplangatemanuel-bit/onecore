# Module delivery checklist

A module is not complete merely because it appears in the catalogue or has a generic record endpoint.

For every module, implement and verify:
- domain data model, migrations, indexes, constraints and retention
- backend services, API contracts, validation, idempotency and error handling
- responsive frontend workflows, accessibility and loading/empty/error states
- tenant/branch-aware permission matrix and negative authorization tests
- approval rules and audit events for sensitive actions
- integration adapters, sandbox/UAT, callback verification, retries and reconciliation
- unit, integration, end-to-end, security, performance, offline and recovery tests as applicable
- monitoring, alerts, backup/restore and rollback
- customer, admin, developer, API and operational documentation
- release approval and customer UAT

Suggested phases from the master specification: (1) core/identity/tenancy/security; (2) Business OS/accounting/inventory/offline POS; (3) payments/eTIMS/tax; (4) website/CMS/media/SEO/search; (5) docs/support/developer/partners/community; (6) industry OS modules; (7) AI/BI/automation; (8) operations/incident/status/release; (9) governance/compliance/DR/scalability.
