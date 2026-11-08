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

Production data is stored in managed PostgreSQL. Supabase PostgreSQL is supported through the backend-only `DATABASE_URL`; see `onecore-ecosystem/docs/SUPABASE.md`. The browser frontend connects only to the authenticated FastAPI API and must never contain Supabase database credentials or a service-role key.

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
