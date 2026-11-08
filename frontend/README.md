# OneCore frontend

React + Vite workspace UI. The frontend is intentionally separate from the FastAPI backend and is deployable as a Vercel project.

## Local development

```bash
npm install
cp .env.example .env
npm run dev
```

Set `VITE_API_BASE_URL` to the backend origin (for example `http://localhost:8000`). The sign-in form uses the backend's OAuth2 form endpoint at `POST /api/v1/auth/login` and fetches the authenticated identity from `GET /api/v1/auth/me`. Access tokens are held in sessionStorage and sent as bearer tokens.

## Build

```bash
npm run build
npm run preview
```

Vite writes the deployable site to `dist/`.

## Database

Production data is stored in Supabase-managed PostgreSQL through the backend `SUPABASE_DB_URL` setting (which takes precedence over `DATABASE_URL`). The frontend connects only to the authenticated FastAPI API; never expose Supabase connection strings or service-role keys through `VITE_*` variables. See `onecore-ecosystem/docs/SUPABASE.md`.

## Vercel

- Import this repository.
- Set **Root Directory** to `frontend`.
- Framework preset: **Vite**.
- Build command: `npm run build`.
- Output directory: `dist`.
- Install command: `npm install`.
- Add `VITE_API_BASE_URL` with the public HTTPS origin of the deployed FastAPI service.
- Redeploy after changing environment variables.

Configure the backend `CORS_ORIGINS` to the exact Vercel production origin (and any intended preview origins), and `TRUSTED_HOSTS` to the backend hostname. Never put backend secrets in Vercel frontend variables: Vite variables are public in the generated JavaScript.

## UI integration status

The shell includes authentication, organization selection/creation, module search/navigation, service status, and workspaces for business operations, industry solutions, platform administration, integrations, reporting and settings. Existing FastAPI-served module interfaces are linked directly to the backend so the current POS, Accounting, CRM, Inventory, Procurement, School and Healthcare pages remain available. Other module entries are clearly identified as workspace shells until their dedicated screens and API contracts are implemented. No fabricated business metrics are presented as live data.


## Production deployment

Set the Vercel project root directory to `frontend` and configure `VITE_API_BASE_URL` to the public HTTPS backend URL. See `DEPLOYMENT.md` at the repository root for the Render + Supabase backend and Vercel frontend release procedure.


## Optional Supabase Auth sign-in

The shared login can also authenticate with Supabase Auth when both `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are configured. The browser uses Supabase Auth for password verification without persisting the Supabase refresh token, then exchanges the short-lived Supabase access token with `POST /api/v1/auth/supabase-session`. The backend verifies the token with the configured Supabase Auth `/auth/v1/user` endpoint, requires a confirmed email, links or provisions a OneCore user, and returns the standard short-lived OneCore API token. Set matching backend `SUPABASE_URL` and `SUPABASE_ANON_KEY` values. Do not use the Supabase service-role key in the browser or this flow.
