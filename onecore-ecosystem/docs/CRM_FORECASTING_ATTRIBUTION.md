# CRM forecasting, quotas, attribution and campaign operations

## Forecasts and quotas

Every open lead can carry an expected close date and optional probability override. Managers configure a probability for every pipeline stage and multipliers for best-case, expected and worst-case scenarios. Monthly, quarterly and annual forecasts group by representative and currency. Currency totals are never combined across currencies. Opportunities without a close date are counted separately.

Best case is gross open pipeline multiplied by the configured best-case multiplier. Expected is probability-weighted open pipeline multiplied by the expected multiplier. Worst case is probability-weighted pipeline multiplied by the worst-case multiplier. Default stage probabilities are illustrative and must be configured by each organization.

Targets are upserted by period, representative/team, branch and currency. Forecast attainment compares expected pipeline with the matching target. Snapshot records are immutable and preserve forecast amount and opportunity count at capture time. Accuracy compares the latest snapshot with won leads that have an actual close timestamp and uses the recorded actual_value when supplied (otherwise the lead estimated value is the initial fallback). New wins capture their close timestamp and initialize actual value from the estimate; managers can correct the realized value. This migration does not invent historical close dates for previously won opportunities.

## APIs

- POST /api/v1/crm/leads/{id}/campaign/{campaign_id} to link a lead to its originating campaign
- PATCH /api/v1/crm/leads/{id}/forecast-details
- POST /api/v1/crm/forecast/settings
- GET /api/v1/crm/forecast/advanced?period_type=month|quarter|year&start_date=YYYY-MM-DD&rep_id=
- POST and GET /api/v1/crm/targets
- POST /api/v1/crm/forecast/snapshots
- GET /api/v1/crm/forecast/accuracy
- POST /api/v1/crm/campaigns/{id}/budget
- POST /api/v1/crm/campaigns/{id}/attributions
- GET /api/v1/crm/campaigns/roi
- POST /api/v1/crm/scheduler/heartbeat and GET /api/v1/crm/scheduler/health

All endpoints use active organization membership and existing read/update/manage permissions. Lead, campaign, contact, order and branch references are tenant/branch scoped. Attribution writes use an organization-unique idempotency key.

## Campaign ROI

A manager links a lead to its originating campaign. Accepted quotes and confirmed sales orders on that lead automatically append idempotent attribution events, linking campaign → lead → quote → sales order. Managers may also record explicit conversion events against a campaign/contact and link a CRM lead and sales order. Order-won and invoice-paid events require a sales-order reference. Revenue is grouped by currency. Set campaign budget before using ROI; zero budget produces a null ROI. This is transparent explicit attribution, not proof of causation or full multi-touch attribution. Receivable invoices can now retain a tenant- and branch-validated CRM sales-order link. When a linked invoice is fully settled, Accounting atomically appends one idempotent `invoice_paid` event tied to the source invoice; multiple invoices for one order are grouped into the same campaign/order revenue. Orders without a campaign link remain un-attributed. Historical invoice backfill and credit-note/refund attribution are not included in this slice.

## Scheduler worker

Docker Compose runs a separate crm-scheduler poller. Configure a dedicated manager service-account bearer token as a secret in .env/secret manager. The worker polls the scheduler endpoint, emits structured logs and posts heartbeats. Run one worker per organization token unless a properly scoped multi-tenant service identity is implemented. Scheduler health reports heartbeat age, due schedules, failed schedules and stale running leases. Worker startup fails closed when its token is missing.

## Provider and production validation

Provider acceptance and delivered callbacks are separate states. Provider credentials, callback authentication, test recipients, sandbox and production smoke tests, bounce/complaint/unsubscribe checks and alert routing must be configured and exercised externally. CI cannot prove live provider delivery. Some provider adapters do not guarantee idempotent delivery; ambiguous network errors may result in duplicate sends.

## Remaining release gates

- Provider sandbox/production UAT and callback authentication per provider.
- Automatically capture actual close timestamps in every lead stage-transition path; legacy wins are not backfilled.
- Backfill historical invoice/payment attribution and publish credit-note/refund events to keep net campaign revenue accurate.
- Advanced dashboard drill-down by source, campaign, product and branch; visual dashboard currently exposes forecast, accuracy, targets, ROI and scheduler health.
- PostgreSQL concurrency/load tests, secret manager setup, multi-organization scheduler orchestration, alert routing, production deployment and business acceptance.
