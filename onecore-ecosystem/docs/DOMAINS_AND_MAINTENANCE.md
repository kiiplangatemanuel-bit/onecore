# Custom domains and maintenance notices

## Custom domains
Organization admins can request a domain with `POST /api/v1/domains` while sending
`X-Organization-ID`. The response includes a TXT challenge at
`_onecore-verification.<hostname>`. Verify with `POST /api/v1/domains/{id}/verify`.
DNS verification uses a TXT lookup; a successful response only changes the domain
to `verified`. It does **not** claim TLS or live routing: an ingress/controller must
provision a certificate, route the host safely, run cross-tenant tests, and then
activate the domain. TLS remains `not_provisioned` until a deployment integration
is added. Unknown hosts must be rejected at the reverse proxy and application edge.

Set a verified domain primary with `POST /api/v1/domains/{id}/primary`. Domain
removal is tenant-scoped. The API never performs arbitrary DNS or HTTP fetches from
user-provided URLs.

## Maintenance notices
Platform administrators can publish an informational notice using
`POST /api/v1/admin/notices`, optionally scoped to an organization, user IDs or
platform roles. Active notices are returned from `GET /api/v1/notices` and users
dismiss them through `POST /api/v1/notices/{id}/dismiss`. Admins can withdraw
notices. Notices are informational and do not impose maintenance restrictions,
pause POS, or block workflows. Scheduling is represented by `starts_at` and
`expires_at`; clients should poll the endpoint and render a non-blocking banner.

## Mandatory attribution
`GET /api/v1/branding/footer` returns the mandatory footer wording. All public and
customer-facing frontend templates must render this server-owned value; tenant
settings must not be allowed to hide or replace it.
