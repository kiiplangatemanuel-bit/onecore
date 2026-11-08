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

The shared sign-in redirect uses a backend-issued, single-use authorization code with PKCE (S256), a 90-second expiry, an exact redirect-origin allowlist, and state verification in the originating portal. The bearer token is exchanged only at the original portal and is never placed in the redirect URL. The browser stores the token in per-origin session storage. This is the OneCore API identity system; it is not Supabase Auth and does not create a shared Supabase browser session.

The public/authenticated layout is implemented, but the following domain-specific private workflows are not yet delivered by this change: Status alert subscriptions and tenant-specific incidents; developer application/API-key/webhook/sandbox lifecycle; private organization documentation; community posting/groups; confidential trust case submission and case tracking; event registration and attendance; careers applicant profiles/applications; partner leads/referrals/agreements. These must not be presented as live until their backend APIs, database models, tenant/role authorization, migrations and tests are implemented. Support attachments are also not enabled by the current support API.

## Supabase and backend

All portal data operations must go through the shared API and the configured Supabase PostgreSQL connection. Never connect browser applications directly with a Supabase service-role key. Public endpoints must expose only explicitly public content; private operations must enforce identity, organization scope and role permissions in the API and database RLS policies where Supabase client access is used.

## Deployment validation

For each portal, build from its own directory, confirm the SPA fallback works on deep links, verify API CORS and health, test public browsing without a session, test sign-in and sign-out, and test that protected API operations reject anonymous or unauthorized users. The portal deployments remain independent; DNS and hosting project creation are owner-operated steps and are not performed by this repository change.
