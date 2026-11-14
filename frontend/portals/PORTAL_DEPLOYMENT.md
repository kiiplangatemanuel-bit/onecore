# Legacy portal source — no independent deployments

OneCore is deployed as one React application from the repository's `frontend/` directory. This folder is retained temporarily for compatibility and migration reference only. Do not create or maintain separate Vercel projects, DNS names, API origins or login experiences for Developers, Documentation, Careers or Partners.

## Unified application

All product and ecosystem capabilities are routes/modules inside the central frontend and share:
- OneCore login and MFA
- The active organization and branch context
- The central FastAPI API and authorization policy
- The single PostgreSQL database
- Shared navigation, notifications, audit and support workflows

Use the main application routes for these functions. Superadmin is available at `/platform`; `/admin/login` is an alias to the same authentication flow.

## Compatibility and retirement

The source files under `frontend/portals/` and any existing external Vercel projects are not automatically removed by this repository change. Do not deploy them as new applications. The deployment owner must verify traffic, redirects, custom-domain ownership and rollback before retiring old projects or DNS records.

## Backend origin allowlists

Configure backend `CORS_ORIGINS` with the exact HTTPS origin(s) of the single main OneCore application and any explicitly approved preview origin. `PORTAL_REDIRECT_ORIGINS` is optional and exists only for legacy PKCE compatibility; it is not required for the unified same-origin login. Never use wildcard CORS with bearer-token authentication.

Never put Supabase service-role keys, database credentials, signing secrets or provider credentials in any `VITE_*` variable.
