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


## Quotes and pipeline forecast increment

- Tenant-owned quotes link to a CRM contact and optionally a lead in the same branch.
- Itemized quote lines include quantity, unit price and operator-entered tax rate.
- Quote totals are calculated server-side using decimal arithmetic.
- Quote lifecycle: draft -> issued -> accepted or rejected; expired quotes cannot be
  accepted. Status changes are audited.
- Quote currency must match the organization's configured base currency.
- A quote detail API returns its complete line breakdown.
- The pipeline forecast groups opportunity value by currency and stage, applying
  explicit fixed probability assumptions (new 10%, qualified 25%, proposal 50%,
  negotiation 75%, won 100%, lost 0%).

### Additional API

- POST /api/v1/crm/quotes
- GET /api/v1/crm/quotes
- GET /api/v1/crm/quotes/{id}
- POST /api/v1/crm/quotes/{id}/issue
- POST /api/v1/crm/quotes/{id}/accept
- POST /api/v1/crm/quotes/{id}/reject
- GET /api/v1/crm/forecast

The /crm workspace includes a basic quote form and lifecycle actions.

### Explicit limitations

Issuing a quote changes its workflow status only; it does not email, SMS or otherwise
deliver the quote to a customer. No customer signature, PDF generation, quote-to-order
conversion, contract, deposit or invoice automation is included. Forecast probabilities
are fixed illustrative assumptions, not learned from historical conversion data.
Campaigns, customer communication, consent management, advanced analytics, team
forecasting, configurable pipeline probabilities and UAT remain outstanding.
