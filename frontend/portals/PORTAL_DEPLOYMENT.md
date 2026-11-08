# Independently deployable OneCore portal frontends

The portal packages live in this repository under `frontend/portals/<portal>`. Each package has its own Vite entry point, dependency manifest, build output and Vercel rewrite configuration. The shared React portal shell is maintained in `frontend/src/PortalApp.jsx` and `frontend/src/portal.css`.

## Portal packages

| Portal | Vercel Root Directory | Portal key |
|---|---|---|
| Support | `frontend/portals/support` | support |
| Status | `frontend/portals/status` | status |
| Developers | `frontend/portals/developers` | developers |
| Documentation | `frontend/portals/docs` | docs |
| Community | `frontend/portals/community` | community |
| Trust | `frontend/portals/trust` | trust |
| Events | `frontend/portals/events` | events |
| Careers | `frontend/portals/careers` | careers |
| Partners | `frontend/portals/partners` | partners |
| Superadmin | `frontend/portals/admin` | admin |

For each Vercel project, select the matching Root Directory, use `npm install` as the install command and `npm run build` as the build command. The output directory is `dist`. Configure production and preview variables independently.

## Required public environment variables

Set `VITE_API_BASE_URL` to the deployed HTTPS API origin. Set the relevant portal URL variables (`VITE_PUBLIC_SITE_URL`, `VITE_APP_URL`, `VITE_ADMIN_URL`, `VITE_DEVELOPER_URL`, `VITE_DOCS_URL`, `VITE_SUPPORT_URL`, `VITE_STATUS_URL`, `VITE_COMMUNITY_URL`, `VITE_TRUST_URL`, `VITE_EVENTS_URL`, `VITE_CAREERS_URL`, `VITE_PARTNERS_URL`) to actual HTTPS origins. These values are public browser configuration, not secrets. An unset or invalid portal destination is rendered as an unavailable configuration link; the frontend does not invent a production destination.

Set backend `CORS_ORIGINS` and `PORTAL_REDIRECT_ORIGINS` to the exact HTTPS origins of every deployed frontend, including the central `app` origin and all nine public portals. The SSO allowlist is checked by the API and must not contain wildcards. Do not use wildcard CORS with bearer-token authentication. Do not put Supabase service-role keys, database credentials, signing secrets or provider credentials in any `VITE_*` variable.

## Public and authenticated access model

All nine public applications use the shared portal shell. Public sections render without an account; the Status portal checks the public `/health` endpoint for API reachability. Support retains its public ticket submission and token-protected guest ticket access plus authenticated ticket history and replies. Authenticated portal views validate the shared OneCore API session with `/api/v1/auth/me` and load only the memberships returned by `/api/v1/organizations`. The organization selector is display context only: it is never treated as authorization, and backend endpoints must independently verify membership and permission.

The shared sign-in redirect uses a backend-issued, single-use authorization code with PKCE (S256), a 90-second expiry, an exact redirect-origin allowlist, and state verification in the originating portal. The bearer token is exchanged only at the original portal and is never placed in the redirect URL. The browser stores the token in per-origin session storage. This is the OneCore API identity system; it is not Supabase Auth and does not create a shared Supabase browser session. PostgreSQL RLS uses the validated OneCore user ID as a transaction-local database setting.

The authenticated portal workflow API now persists typed records for Status alert preferences, developer application/webhook/sandbox configuration, organization guides, community posts/comments/groups/profiles, confidential Trust reports, event registrations/bookings/attendance, applicant profiles/applications, and partner profiles/referrals/leads/agreements/resources. Organization records are filtered by active membership and `organization` visibility; private records are owner-only; Trust cases are visible only to their owner and `security_admin`/`root_superadmin`, while Careers applications are visible only to their applicant and `recruitment_admin`/`root_superadmin`. Platform administrators can publish allowlisted public content through a protected API. This is a workflow-record foundation, not the final integration layer: webhook delivery/retries/signature verification, outbound alert dispatch, event payment processing, applicant email automation, partner agreement e-signature, moderation/approval queues and public-content frontend CMS controls remain outstanding. Support now has private presigned attachment workflows with a manual quarantine review gate.

## Supabase and backend

All portal data operations must go through the shared API and the configured Supabase PostgreSQL connection. Never connect browser applications directly with a Supabase service-role key. Public endpoints expose only explicitly public content. Migrations 0052 and 0054–0056 add PostgreSQL RLS for portal workflow records, Support tickets/messages/attachments and developer API credentials/usage. The shared identity is currently OneCore JWT, not Supabase Auth; configure a dedicated PostgreSQL runtime role with NOBYPASSRLS and verify the live Supabase role before relying on RLS in production.

## Deployment validation

For each portal, build from its own directory, confirm the SPA fallback works on deep links, verify API CORS and health, test public browsing without a session, test sign-in and sign-out, and test that protected API operations reject anonymous or unauthorized users. The portal deployments remain independent; DNS and hosting project creation are owner-operated steps and are not performed by this repository change.


## Authenticated portal workflow API (migration 0052)

Apply `alembic upgrade head` to create `portal_workflow_records`. The shared API exposes:
- `GET /api/v1/portals/{portal}/public/{record_type}`: allowlisted, global, public and published content only; no organization records are returned.
- `GET /api/v1/portals/{portal}/records?record_type=...&organization_id=...: authenticated records; organization records require an active membership and `visibility=organization`, while personal/private records are owner-scoped.
- `POST /api/v1/portals/{portal}/records/{record_type}` and `PATCH /api/v1/portals/{portal}/records/{id}`: validated record creation and limited lifecycle changes with role checks and audit events.
- `POST /api/v1/portals/admin/{portal}/public/{record_type}`: platform-admin-only publication for the explicit public content allowlist.

The frontend `PortalWorkflowWorkspace` connects the authenticated views to these APIs. The API never accepts a caller-supplied owner ID, does not permit personal Trust/Careers records to be attached to a tenant, and recursively rejects credential-like keys in JSON payloads. The migration enables and forces PostgreSQL RLS on `portal_workflow_records` with separate SELECT, INSERT and UPDATE policies; DELETE is denied. `current_user` sets a transaction-local `app.user_id` only after validating the OneCore JWT, and SQLAlchemy reapplies it after each transaction boundary. RLS protects access only when the configured database role does not have `BYPASSRLS` (superusers always bypass RLS). Production must use a dedicated least-privilege application role with `NOBYPASSRLS`, and verify that role against Supabase before treating database RLS as an effective production boundary. Never expose direct browser database access or Supabase service-role credentials.


## Developer API credentials (migration 0056)

The Developers portal now issues organization-scoped API credentials through authenticated backend routes:
- `POST /api/v1/developer/api-keys`: create a key for an active organization as an `org_admin` or `developer`. The plaintext secret is returned once; only its SHA-256 digest is stored.
- `GET /api/v1/developer/api-keys?organization_id=...`: list key metadata without secrets. Developers see their own keys; organization administrators see organization keys.
- `POST /api/v1/developer/api-keys/{id}/revoke`: immediately revoke an owned or organization-managed key.
- `GET /api/v1/developer/api-keys/{id}/usage`: view recorded API request history.
- `GET /api/v1/developer/v1/organization`: example API-key-protected endpoint requiring `organization:read` and the `X-OneCore-API-Key` header.

Keys expire after 90 days by default (configurable at issuance up to 365 days), are checked against current organization membership on every API-key-authenticated request, and are covered by database RLS and audit events. The `sandbox`/ `production` value currently labels the credential; it does not yet provide a separate sandbox database or data plane. Do not use sandbox-labelled keys as evidence of production-data isolation. The current example endpoint records successful authenticated usage; usage instrumentation must be added to each additional API route as it is brought under API-key authentication.

## Support attachments (migrations 0054–0055)

Support attachments use a private S3-compatible bucket. The API creates short-lived presigned upload/download URLs, validates file metadata, and quarantines completed uploads as `pending_scan`. Downloads remain blocked until a platform support administrator records an explicit review decision. This is a manual release gate, not automated malware scanning. Configure the bucket privately and set exact portal-origin CORS for PUT and Content-Type; never expose storage credentials to the browser.


## Developer webhook delivery worker

Developer webhook configurations are created in the authenticated Developers portal. An organization Developer or Administrator activates each configured endpoint; the signing secret is displayed once and stored encrypted at rest using a key derived from the API `SECRET_KEY`. Keep `SECRET_KEY` stable across deployments and backups or existing encrypted webhook secrets cannot be decrypted. Rotate secrets after any suspected exposure.

The API writes events to the durable `developer_webhook_deliveries` outbox with an endpoint/event idempotency constraint. Deliveries are signed using HMAC-SHA256 over `timestamp + "." + exact_raw_body` and sent with `X-OneCore-Event`, `X-OneCore-Event-Id`, `X-OneCore-Timestamp`, and `X-OneCore-Signature: sha256=...` headers. Receivers must compare signatures in constant time, reject stale timestamps (recommended maximum age: five minutes), and deduplicate event IDs. Delivery retries use exponential backoff, stop after eight attempts, do not follow redirects, and use bounded connection/request timeouts.

Apply Alembic migration 0057 after 0056. Run the worker as a separate process, not as a public unauthenticated API route:

```bash
cd onecore-ecosystem
python -m app.workers.webhook_delivery --batch-size 25
```

Schedule that command every minute using the deployment platform's worker/cron facility. Multiple worker instances may run concurrently; PostgreSQL row locks with `SKIP LOCKED` prevent two workers from claiming the same pending delivery in the same transaction. The worker requires the same database connection and `SECRET_KEY` as the API. Configure network egress policy as an additional SSRF boundary; endpoint DNS is checked for public addresses at activation and immediately before delivery, redirects and environment proxies are disabled. DNS pinning/network-level egress enforcement remains a deployment responsibility.
