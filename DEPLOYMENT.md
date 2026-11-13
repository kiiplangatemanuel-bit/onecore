# Deploy OneCore backend and frontend

## Backend — Render + Supabase

1. Create a Supabase project and copy its PostgreSQL connection URI from **Project Settings → Database**. Use the Supavisor session pooler or direct connection where supported, and append `sslmode=require`.
2. Connect this GitHub repository to Render and select the repository Blueprint. Render reads the root `render.yaml` and builds the backend using `onecore-ecosystem/Dockerfile`.
3. Set the secret `SUPABASE_DB_URL` on the Render `onecore-api` service. Use the actual Supabase URI; do not commit it or expose it to Vite.
4. Set `CORS_ORIGINS` to the exact deployed Vercel origins, comma-separated, with no wildcard. Include the main OneCore website/application and the four independent portal origins: Developers, Documentation, Partners and Careers. Support, Trust, Community, Status and Events are same-origin routes on the main website and need no separate origins.
5. Set `PORTAL_REDIRECT_ORIGINS` to the exact HTTPS origins of the four independent portals only. The main-site modules use same-origin authentication and are not separate PKCE redirect origins. The shared sign-in flow uses short-lived, single-use PKCE authorization codes and rejects unregistered redirect origins. If you attach a custom API domain, update `TRUSTED_HOSTS` to include that hostname.
6. Review generated `SECRET_KEY`; keep `APP_ENV=production`, `DEBUG=false`, and `FORCE_HTTPS=true`.
7. Deploy and wait for Render's `/ready` health check. The container runs `alembic upgrade head` before starting Uvicorn. Confirm the migration head in the deployment logs.
8. Create the first organization/admin through the supported onboarding/bootstrap process. Do not set bootstrap credentials unless you can rotate/remove them immediately after first use.

## Frontend — Vercel

1. Import this repository into Vercel.
2. Set **Root Directory** to `frontend`.
3. Set `VITE_API_BASE_URL` to the public HTTPS Render API URL (for example, `https://onecore-api.onrender.com`). This is a public API origin, not a secret.
4. Deploy. Vercel uses `frontend/vercel.json` to route SPA paths to `index.html`.
5. Copy the exact Vercel production origin into Render's `CORS_ORIGINS`, save, and redeploy the API if required.

## Release checks

- Confirm Render reports healthy at `/ready` and API `/health` responds.
- Confirm Vercel's `/login` and `/procurement` routes load.
- Sign in, select an organization and verify Procurement lists, supplier/requisition/PO creation, approval permissions, GRN inspection and accounting reconciliation.
- Test Supabase backups/PITR and restore in a staging project before production data migration.
- Configure M-Pesa/Daraja B2C, email/SMS/WhatsApp and bank credentials only after provider onboarding; leave each integration disabled until its credentials, callback URLs and UAT are complete.

A GitHub PR passing CI is not a live deployment. Render/Vercel account authorization, Supabase project credentials, DNS, provider credentials and final production smoke tests must be completed by an authorized project owner.
