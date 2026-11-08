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

Set backend CORS to the exact origins of every deployed frontend. Do not use wildcard CORS with bearer-token authentication. Do not put Supabase service-role keys, database credentials, signing secrets or provider credentials in any `VITE_*` variable.

## Current implementation boundary

The packages currently share a public/authenticated portal shell and use the existing OneCore API login and `/auth/me` identity endpoint. The Superadmin portal additionally calls the existing `/api/v1/admin/overview` endpoint, which enforces the backend platform-admin role. This is not yet a full SSO implementation: the existing frontend stores bearer tokens in per-origin session storage, so signing into one subdomain does not automatically sign a user into another. Cross-domain SSO requires a backend-issued, short-lived, single-use authorization-code exchange (or a shared Supabase Auth session) and explicit allowed redirect origins.

Likewise, the portal shells do not pretend that missing domain workflows are live. Ticket creation and replies, status subscriptions and incident management, developer application/key lifecycle, community posts, trust disclosures, event bookings, careers applications and partner CRM workflows need their dedicated backend APIs, database models, permissions, migrations and tests before being enabled. The current public/authenticated portal structure is the deployment and UI foundation for those modules.

## Supabase and backend

All portal data operations must go through the shared API and the configured Supabase PostgreSQL connection. Never connect browser applications directly with a Supabase service-role key. Public endpoints must expose only explicitly public content; private operations must enforce identity, organization scope and role permissions in the API and database RLS policies where Supabase client access is used.

## Deployment validation

For each portal, build from its own directory, confirm the SPA fallback works on deep links, verify API CORS and health, test public browsing without a session, test sign-in and sign-out, and test that protected API operations reject anonymous or unauthorized users. The portal deployments remain independent; DNS and hosting project creation are owner-operated steps and are not performed by this repository change.
