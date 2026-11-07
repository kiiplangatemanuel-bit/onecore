# CRM contacts and sales pipeline

This increment adds the first OneCore CRM vertical slice. It is not a complete sales
automation, marketing or customer service suite.

## Capabilities

- Tenant-owned contacts with normalized email and phone duplicate checks.
- Optional branch assignment and branch-scope filtering.
- Sales leads with source, stage, estimated value, currency, assignment and next step.
- Explicit lead-stage transition rules.
- Follow-up activities (call, email, meeting, task, note) linked to exactly one
  tenant contact or lead.
- Activity completion timestamps and audit events.
- Tenant membership checks for assigned sales owners.
- API and basic accessible workspace at `/crm`.

## API

- `GET/POST /api/v1/crm/contacts`
- `GET/POST /api/v1/crm/leads`
- `PATCH /api/v1/crm/leads/{id}/stage`
- `GET/POST /api/v1/crm/activities`
- `POST /api/v1/crm/activities/{id}/complete`

All operations require bearer authentication and active organization membership.
Reads require read permission, creation requires create permission, and stage/activity
updates require update permission. Records are filtered by tenant and branch. A
contact or lead linked to an activity must belong to the active tenant and be within
the user's branch scope.

Lead stages are new, qualified, proposal, negotiation, won and lost. Transitions are
controlled: new to qualified/lost; qualified to proposal/negotiation/lost; proposal
to negotiation/won/lost; negotiation to proposal/won/lost; lost may be reopened to
new; won is terminal. A stage change creates an audit event.

## Explicit gaps

- Opportunity products/quotes, proposals, contracts and sales order conversion.
- Customer segmentation, campaigns, consent/preferences, marketing automation and
  communication-provider delivery.
- Pipeline forecast, weighted revenue, conversion analytics and configurable stages.
- Contact merge/deduplication review, full search/filter/pagination/import/export.
- Role-based ownership/team sharing, reassignment approvals and SLA escalation.
- Contact edit/archive, complete activity timeline, calendar and reminders.
- Automated email/SMS/WhatsApp delivery and consent audit.
- Full branch-isolation integration tests, PostgreSQL concurrency, security review,
  accessibility audit and UAT.
