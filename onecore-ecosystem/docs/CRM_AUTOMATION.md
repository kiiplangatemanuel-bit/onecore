# CRM campaign automation and communications

## Templates
Reusable email, SMS and WhatsApp templates are organization/branch scoped and
versioned. Saving an existing name creates a new version and deactivates the prior
version; schedules retain the exact template version selected when created.
Supported safe placeholders are `{{first_name}}`, `{{last_name}}`,
`{{full_name}}`, `{{email}}`, `{{phone}}`, `{{company}}` and
`{{campaign_name}}`. No template expressions are evaluated as code. A scheduled
run fails visibly if a pinned template version or declared placeholder is invalid.

## Audience segmentation
Saved segments support nested `all` (AND) and `any` (OR) groups to depth 3,
with up to 20 conditions per group. Allowed contact fields are full_name, email,
phone and company. Operators are eq, ne, contains, starts_with, ends_with,
is_empty, not_empty and in. Values are validated and parameterized; arbitrary SQL,
expressions and code are not accepted. Preview reports the total matching count
and a sample. Segments can be edited or deactivated. If a schedule's segment is
deactivated, the worker marks the schedule failed instead of silently widening
the audience.

## Scheduling
POST `/api/v1/crm/campaigns/{campaign_id}/schedule` accepts an ISO-8601
timezone-aware `scheduled_at`, IANA `timezone`, recurrence `once`, `daily`
or `weekly`, and optional `template_id` and `segment_id`. A child campaign
is created for each occurrence with recipient-level rendered subject/body
snapshots. Each occurrence re-evaluates the saved segment and the latest channel
and purpose consent at dispatch time. Revoked and expired opt-ins are suppressed.
The existing delivery worker's stable provider idempotency keys, attempt cap,
provider callbacks and reporting are reused.

Schedule controls:
- GET `/api/v1/crm/schedules`
- POST `/api/v1/crm/campaigns/{id}/schedule/pause`
- POST `/api/v1/crm/campaigns/{id}/schedule/resume`
- DELETE `/api/v1/crm/campaigns/{id}/schedule`
- POST `/api/v1/crm/scheduler/run-due` for an authorized manual/administrative run

## Worker operation
Run from `onecore-ecosystem`:
`python -m app.workers.crm_scheduler`.
Docker Compose runs `crm-scheduler` alongside the API and mounts the same database
volume. Compose defaults to the shared SQLite file under `/app/data`; set
`ONECORE_DATABASE_URL` in `.env` to use an external PostgreSQL database. The worker polls every five seconds, claims due rows with leases, renews
leases between small provider batches, stores failure details and recovers stale
running schedules. Daily/weekly recurrence preserves local wall-clock time across
daylight-saving transitions. It snapshots at most 5,000 eligible contacts per
occurrence; review preview truncation before scheduling large audiences.

SQLite does not provide the row-level `skip_locked` behavior used for concurrent
claims: run exactly one scheduler worker with SQLite. Use PostgreSQL for multiple
workers. Schedule owners must retain an active organization membership and campaign
management permission; otherwise the run fails with an operator-visible error.

## Production requirements
Configure verified sender identities and email/SMS/WhatsApp credentials, public
HTTPS unsubscribe/callback URLs, callback secrets, consent evidence and provider
sandbox/production UAT. Scheduling does not bypass channel-specific consent or
provider configuration. Campaign dispatch is asynchronous and is not executed in
the scheduling HTTP request.
