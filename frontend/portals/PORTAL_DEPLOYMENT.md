# OneCore frontend deployment topology

OneCore is delivered as one main website/application plus four independently deployable portals. The main website owns the integrated customer-facing modules; they are not standalone Vercel projects.

## Independent portal deployments

| Portal | Vercel Root Directory | Portal key |
|---|---|---|
| Developers | `frontend/portals/developers` | developers |
| Documentation | `frontend/portals/docs` | docs |
| Careers | `frontend/portals/careers` | careers |
| Partners | `frontend/portals/partners` | partners |

Each independent portal uses the shared React portal shell in `frontend/src/PortalApp.jsx` and `frontend/src/portal.css`. Build from its own directory with `npm install` and `npm run build`; output directory is `dist`.

## Modules hosted inside the main OneCore website

These routes are served by the main frontend build and use the same OneCore identity, shared API client, backend and database. They must not have independent Vercel projects, DNS records or separately configured browser API origins:

| Module | Main website route | Shared workflow key |
|---|---|---|
| Support | `/support` | `support` |
| Trust | `/trust` | `trust` |
| Community | `/community` | `community` |
| Status | `/status` | `status` |
| Events | `/events` | `events` |
| Admin / Superadmin | `/admin` | `admin` |

The main frontend mounts the existing portal workflow UI at these routes. Public visitors can access public content; authenticated actions continue to use the existing OneCore API session, organization membership checks and backend authorization. Admin routes remain protected by the backend platform-role checks.

## Legacy deployment retirement

The former standalone Support, Status, Community, Trust, Events and Admin frontend directories are legacy compatibility entry points only. They are excluded from the independent portal CI build matrix and must not be used as Vercel root directories for new deployments. Existing hosting projects and DNS records must be retired or redirected by the deployment owner after the main-site routes are deployed and smoke-tested. Do not delete old projects or DNS until traffic has been verified on the main website.

## Required public environment variables

Set `VITE_API_BASE_URL` to the deployed HTTPS API origin. Set `VITE_PUBLIC_SITE_URL` to the main OneCore website origin on all four independent portal deployments. Set `VITE_APP_URL` only when the authenticated customer workspace is hosted at a distinct origin; otherwise the shared login falls back to the main website. Configure only these independent portal origins: `VITE_DEVELOPER_URL`, `VITE_DOCS_URL`, `VITE_CAREERS_URL` and `VITE_PARTNERS_URL`. Integrated modules resolve to same-origin paths on the main website and do not use separate `VITE_SUPPORT_URL`, `VITE_TRUST_URL`, `VITE_COMMUNITY_URL`, `VITE_STATUS_URL`, `VITE_EVENTS_URL` or `VITE_ADMIN_URL` values.

Set backend `CORS_ORIGINS` and `PORTAL_REDIRECT_ORIGINS` to the exact HTTPS origins of the main website and the four independent portals. Do not add the retired integrated-module origins to allowlists after their redirects and traffic migration are complete. Do not use wildcard CORS with bearer-token authentication. Never put Supabase service-role keys, database credentials, signing secrets or provider credentials in any `VITE_*` variable.

## Shared identity, API and database

All portal and integrated-module data operations go through the shared FastAPI API and configured Supabase PostgreSQL connection. Browser applications must never connect using database credentials or a Supabase service-role key. The main website and all four independent portals use the same OneCore identity and short-lived bearer-token model. The organization selector is display context only; every backend endpoint independently verifies membership and permissions.

The authenticated workflow API persists typed records for Status alert preferences, developer application/webhook/sandbox configuration, organization guides, community posts/comments/groups/profiles, confidential Trust reports, event registrations/bookings/attendance, applicant profiles/applications, and partner profiles/referrals/leads/agreements/resources. The workflow-record foundation does not imply all downstream integrations are complete: webhook delivery/retries/signature verification, outbound alert dispatch, event payment processing, applicant email automation, partner agreement e-signature, moderation/approval queues and public-content CMS controls remain separately tracked work. Support attachments use private presigned workflows with a manual quarantine review gate.

## Validation and retirement sequence

1. Deploy the main website with the integrated routes and SPA fallback.
2. Verify each integrated route on the main website, including public access and authenticated workflows.
3. Verify Support guest ticket access, authenticated ticket history and replies.
4. Verify Trust confidentiality, Community moderation permissions, Events registration/attendance, and Status health/incident behavior.
5. Verify Admin/Superadmin rejects users without the required platform role.
6. Deploy and smoke-test only the four independent portals.
7. Update CORS and SSO redirect allowlists to the main website plus the four independent portal origins.
8. Redirect/retire legacy integrated-module hosting projects and DNS only after traffic verification.

DNS, Vercel project deletion, domain redirects and production environment updates are owner-operated deployment actions; a repository change cannot perform them.
