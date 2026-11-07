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



## Accepted quote to sales order conversion increment

An accepted, unexpired CRM quote can be converted once into a confirmed sales order.
Conversion snapshots every quote line, quantity, unit price, tax rate and calculated
amount into order lines. The source quote is unique per sales order, so repeat requests
return the existing order rather than creating duplicates. The generated default
order number is `SO-{quote_number}`; callers may supply an organization-unique order
number. All records are tenant-scoped and branch access is checked before conversion.

### Additional API
- `POST /api/v1/crm/quotes/{id}/convert-to-order`
- `GET /api/v1/crm/orders`
- `GET /api/v1/crm/orders/{id}`

This is an internal order record only. It does not reserve or deduct inventory,
create an invoice, collect a deposit, dispatch goods, or send a customer notification.
Those require fulfillment, accounting and provider workflows. Migration
`0020_crm_sales_orders` adds sales order headers and immutable line snapshots.



## Marketing consent and campaign preparation increment

- Contact consent is stored as append-only channel/purpose decisions. A later revocation
  supersedes an earlier grant because campaign preparation evaluates the latest event
  for each contact/channel/purpose.
- Consent records capture the source, actor, timestamp and optional expiry.
- Draft email/SMS/WhatsApp campaigns can be created and prepared by organization
  managers. Preparation snapshots only contacts with current, unexpired granted
  marketing consent and a usable channel address.
- Branch access is applied to campaign and recipient selection. Campaign preparation
  is idempotent after the campaign enters `ready`.
- APIs: POST/GET `/crm/contacts/{id}/consents`, POST/GET `/crm/campaigns`,
  GET `/crm/campaigns/{id}`, POST `/crm/campaigns/{id}/prepare`.

Preparation does not send messages. No email/SMS/WhatsApp provider, unsubscribe
webhook, delivery callback, campaign scheduling worker, suppression-list service,
consent import evidence or delivery analytics is connected. A future dispatcher must
re-check the latest consent immediately before every send; prepared recipient snapshots
are not a permanent authorization to deliver. Review privacy and local legal obligations
before enabling real campaigns.
