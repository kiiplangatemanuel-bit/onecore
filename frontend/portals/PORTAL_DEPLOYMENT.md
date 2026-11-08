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

The shared sign-in redirect uses a backend-issued, single-use authorization code with PKCE (S256), a 90-second expiry, an exact redirect-origin allowlist, and state verification in the originating portal. The bearer token is exchanged only at the original portal and is never placed in the redirect URL. The browser stores the token in per-origin session storage. When Supabase Auth is configured, the central login and registration forms use Supabase Auth; the API verifies Supabase JWTs using the project's JWKS or the server-only SUPABASE_JWT_SECRET for legacy HS256 projects, and links verified identities to OneCore users. The cross-domain portal code exchange still issues a short-lived OneCore API token for the destination origin.

The API now provides allow-listed, owner- and tenant-scoped portal workflow records for Status, Developers, Documentation, Community, Trust, Events, Careers and Partners; explicit public feeds expose only global records marked public and published. Platform administrators can create, edit, publish and unpublish public content. Authenticated portal workspaces can create, list and withdraw private records. Organization membership is revalidated even for the record creator, and resource-type role gates are enforced by the backend. Confidential Trust and partner agreement payloads are encrypted at rest using a key derived from SECRET_KEY.

This is a shared workflow-record foundation, not a claim that every specialist integration is complete. Dedicated API-key issuance/rotation and API-key authentication, signed webhook delivery/retry, real status alert delivery, event capacity/payment/attendance scanners, secure file attachments, applicant CV storage/recruitment approvals, partner agreement e-signature and Supabase RLS policies still require dedicated implementations and provider/storage configuration. Do not treat generic workflow records as a substitute for those specialized controls.

## Supabase Auth and database

Set backend SUPABASE_URL to the Supabase project URL. For projects using legacy HS256 signing, set SUPABASE_JWT_SECRET as a server-only secret; for asymmetric signing, the API verifies against the project's published JWKS endpoint. Never expose SUPABASE_JWT_SECRET or a service-role key to Vite. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in each frontend deployment to enable Supabase Auth sign-in and signup. The Supabase email-confirmation redirect must allow the central app's /login URL. Existing OneCore accounts are linked to a verified Supabase identity by exact email; newly verified Supabase users receive a OneCore identity and must complete organization onboarding before tenant access is granted.

All portal data operations must go through the shared API and the configured SUPABASE_DB_URL. Never connect browser applications directly with a Supabase service-role key. Public endpoints expose only explicitly public, published global content. Private operations enforce identity, active organization membership, owner and role scope in the API. The current API connects as a backend database role; Supabase RLS policies for direct browser access are not part of this implementation and direct browser table access must remain disabled.

## Deployment validation

For each portal, build from its own directory, confirm the SPA fallback works on deep links, verify API CORS and health, test public browsing without a session, test sign-in and sign-out, and test that protected API operations reject anonymous or unauthorized users. The portal deployments remain independent; DNS and hosting project creation are owner-operated steps and are not performed by this repository change.
