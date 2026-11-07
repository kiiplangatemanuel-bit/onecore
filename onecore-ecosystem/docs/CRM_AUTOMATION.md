# CRM campaign automation

## Templates
- Create reusable, organization- and optionally branch-scoped email, SMS and WhatsApp templates.
- Template edits create a new version; schedules retain the selected immutable version.
- Supported safe placeholders: `{{first_name}}`, `{{last_name}}`, `{{full_name}}`,
  `{{email}}`, `{{phone}}`, `{{company}}`, `{{campaign_name}}`.
- Unsupported variables fail the scheduled run rather than being interpreted as code.

## Audience segmentation
Saved segments support nested AND/OR groups (maximum depth 3 and 20 conditions per
group). Supported contact fields are full_name, email, phone and company. Operators
are eq, ne, contains, starts_with, ends_with, is_set and in. No arbitrary SQL, JSON
paths, expressions or executable rules are accepted. Preview is tenant/branch scoped
and reports matched/addressable counts. Current scheduled recipient preparation
rechecks the latest channel/purpose consent and excludes expired/revoked opt-ins.

## Scheduling and worker
Create a draft campaign through the CRM workspace, then POST
`/api/v1/crm/campaigns/{id}/schedule` with timezone-aware scheduled_at, an IANA
timezone, recurrence once/daily/weekly and optional template_id/segment_id.
The scheduler creates a distinct child campaign per occurrence, snapshots each
recipient's rendered subject/body, and uses the existing consent revalidation,
provider idempotency, delivery callback, retry cap and audit path.

Run the independent worker from the application directory:
`python -m app.workers.crm_scheduler`.
Keep one or more worker processes supervised by the deployment platform. Row locks,
a ten-minute lease and unique campaign run numbers prevent concurrent workers from
creating duplicate occurrences. The worker processes due rows every five seconds.
Pause/resume endpoints are available. A one-time schedule becomes completed; daily
and weekly schedules calculate the next future occurrence without replaying every
missed interval after downtime.

Scheduled campaigns do not send from the web request. Provider credentials,
callback configuration, sender verification, consent evidence and live provider UAT
remain required before production use. Delivery analytics are available per child
campaign occurrence through the existing campaign report endpoint.
