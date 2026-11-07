# OneCore implementation status

Scope baseline: the supplied master specification defines 75 functional categories and
requires a feature to have its data/configuration, backend, frontend, permissions,
validation, tests, monitoring, documentation and deployment evidence before it is
marked complete.

## Verified in this delivery

The following are implemented in the shared modular-monolith foundation and have
passed the repository CI test workflow at the recorded commits:

- JWT login/current-user lookup and Argon2 password verification (existing baseline).
- Tenant membership lookup and role-based permissions for generic record operations.
- Branch scope filtering for records; record create, list, update and delete.
- Organization branch model and tenant-scoped create/list/update/deactivate APIs.
- Organization invitation creation, listing, revocation and acceptance; token hashes
  are stored, expiry is checked, and acceptance requires the invited account email.
- Custom-domain request, DNS TXT ownership verification, TLS certificate check before
  platform activation, primary-domain selection and tenant-safe organization lookup.
- Informational maintenance notices with organization/user/platform-role targeting,
  scheduling, dismissal, draft editing, second-admin publication approval and withdrawal.
- Mandatory footer API wording and public homepage attribution.
- CI workflow for dependency installation, Python compilation and pytest.

## Verification evidence

- CI workflow: .github/workflows/onecore-ci.yml.
- A successful run after the explicit package-path fix:
  4bd2ac2222ce975f9dfc5f9aab7704ab14f6a284.
- A successful run after invitations and branch APIs:
  b4097d650626575a697f49314119f01b6b5db9ad.
- Newer documentation-only commits trigger the same workflow; check the Actions tab
  for the latest run before release.

## Not complete / production blockers

The 75-category register and module folders are scope/catalogue assets, not 75
implemented business applications. The specialist module directories still need
their own domain schemas, migrations, services, UI, authorization matrix, tests,
monitoring, documentation and user acceptance testing.

Shared platform work still outstanding includes:

- Production email delivery and email verification; password reset; MFA/TOTP and
  recovery codes; SSO/OIDC; session/device inventory and revocation; throttling and
  account lockout.
- A dedicated organization/branch administration frontend and verified branch
  existence in branch-scope assignment/invitation UX.
- Domain ingress provisioning, automated certificate issuance/renewal, primary-domain
  redirects and end-to-end custom-host deployment tests. The API checks an already
  provisioned HTTPS certificate; it does not provision TLS or configure DNS.
- A notification delivery worker, WebSocket/SSE push and fallback polling UI.
- Alembic migrations; production PostgreSQL/Redis/object storage setup; backup/PITR,
  tested restore, monitoring, alerting, incident runbooks and rollback.
- Security review, load/performance/accessibility testing and production deployment.
- Complete frontend experiences for every enabled module and required responsive
  English/Kiswahili content.
- Provider-specific M-Pesa, KRA eTIMS, SHA, bank, messaging and AI sandbox/UAT;
  no adapter should be called certified or live without formal provider approval.

## Release policy

Do not expose a module as production-ready merely because it exists in the catalogue.
Keep specialist modules disabled until their own acceptance evidence is complete.
Do not use the generic JSON record API as a substitute for accounting, clinical,
tax, payroll, school grading, lending or offline-POS domain logic.


## Database migration foundation (added 7 November 2026)

- Added Alembic configuration and an explicit initial revision, `0001_initial`,
  covering the existing shared-platform tables (users, organizations, memberships,
  branches, records, audit events, custom domains, notices, dismissals and invitations).
- Added migration environment with SQLAlchemy metadata registration and configured
  database URL from application settings.
- Removed implicit `Base.metadata.create_all()` from API startup; schema evolution
  now uses reviewed, versioned migrations.
- Docker startup runs `alembic upgrade head` before launching Uvicorn.
- CI installs Alembic, applies the migration, tests downgrade to base and re-upgrade,
  then runs compilation and pytest.
- Operator instructions: `onecore-ecosystem/docs/DATABASE_MIGRATIONS.md`.
- CI runs for the migration changes were still running at the time this tracker was
  updated. Do not treat migration verification as passed until the Actions runs
  attached to the commits below finish successfully.
- Commits: `28acbc5` (config), `37cc3c6` (environment), `f7284fa` (initial
  migration), `163f46f` (dependency), `399e339` (startup), `2682f76` (CI),
  `14db2f3` (container startup), `26afe65` (operator documentation).

Remaining database work: production PostgreSQL migration rehearsal, data backup and
restore/PITR procedures, migration lock/concurrency strategy, monitoring and a
reviewed upgrade/rollback runbook. The initial migration establishes the current
shared schema only; specialist product schemas and domain migrations remain unbuilt.
