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


### Migration CI regression and correction

- The first migration CI runs confirmed that Alembic upgrade, downgrade and re-upgrade
  all succeeded. The pytest step then failed in 2 existing smoke tests because the
  migration command ran from `onecore-ecosystem` while pytest ran from the repository
  root, causing the relative SQLite URL to point at a different empty database.
- Corrected the workflow to execute pytest with `onecore-ecosystem` as its working
  directory, matching the migration command and application database path.
- Correction commit: `2663254`. Its CI run was queued at tracker update time;
  success is not yet verified. The earlier failed run is retained as evidence rather
  than being represented as a pass.


## Inventory vertical slice (7 November 2026)

Implemented on main:

- Tenant-scoped inventory product catalogue with organization/SKU uniqueness.
- Decimal-based append-only stock movement ledger and derived branch balances.
- Receipt, issue and adjustment rules; negative resulting balances are rejected.
- Branch ownership and membership branch-scope checks for inventory movement and
  stock queries.
- Per-tenant idempotency key with duplicate replay handling and conflicting-payload
  rejection.
- Audit events for product creation and stock movement posting.
- API: GET/POST `/api/v1/inventory/products`, GET `/api/v1/inventory/stock`,
  POST `/api/v1/inventory/movements`.
- Accessible basic inventory UI at `/inventory`; bearer token held in page memory.
- Migration `0002_inventory`; domain rules extracted to
  `app/services/inventory.py`; documentation in `docs/INVENTORY.md`.
- Automated tests cover movement direction, decimal balance arithmetic, negative
  stock prevention, model/index contracts, input validation and route registration.

Key commits: `7715fb8` (models), `34a674d` (decimal quantities), `cf7f8eb`
(schemas), `80192aa` (migration), `67c7d8c` (API), `dc326a3` (domain service),
`d956580` (service wiring), `66c15d2` and `8ec3360` (tests), `7794f11` and
`c9f8535` (UI), `baf6757` (inventory documentation).

Verification note: after correcting the CI working-directory mismatch, the workflow
run for commit `4ef6b55` passed. Inventory-specific CI runs for commits
`8ec3360` and `baf6757` were still running/queued when this status entry was
written; do not treat the inventory test suite as verified until the latest run
completes successfully.

Inventory still incomplete: purchasing/procurement, supplier and purchase-order
workflows, warehouse transfers, batch/lot/serial/expiry, reservations, costing and
valuation, stocktakes, advanced reporting, full edit/deactivate UI, PostgreSQL
concurrency/load testing, and end-to-end branch isolation tests.

## Current scope decision

The user requested full Accounting, CRM, Inventory, Procurement, POS, offline POS,
School, Hospital, Pharmacy, Laboratory, SACCO, Microfinance, payment/provider
integrations, identity, superadmin/subscriptions/workflows/analytics, operations,
frontend, accessibility, security and UAT. These are separate large products and
platform capabilities. This delivery implements only the inventory catalogue and
stock-ledger slice above; all other listed areas remain unimplemented or partial
unless independently evidenced elsewhere in this tracker. No M-Pesa, KRA eTIMS or
SHA provider connection, provider certification, live payment, production hosting,
TLS provisioning or UAT approval is claimed.


### Inventory CI regression and correction

- Inventory CI run `42361756874` completed with 24 passing tests and one failure.
  The failure was in the new route-registration test: current FastAPI exposes a lazy
  included-router object without a direct `.path` attribute.
- Updated the test to inspect the generated OpenAPI path map instead. Correction
  commit: `68b7904`. Its CI result is pending; verify before treating the inventory
  slice as passing.


### Verified inventory CI result

- Corrected inventory test run: commit `68b79041c2ea5aa2afcfe82f22a91abb81418f12`.
- GitHub Actions run `42361801378` completed successfully: migrations upgraded,
  downgraded and upgraded again; Python compilation passed; pytest reported
  **25 passed, 5 warnings**.
- The subsequent tracker-only commit may trigger another run; the above is the
  recorded code verification result for the inventory test correction.


### Latest inventory UI and retry hardening verification

- Added UI support for negative stock adjustments through an explicit increase /
  decrease selector (`b080c5f`).
- Idempotent movement replay now also compares the movement reference field
  (`af299e4`).
- GitHub Actions run `42361861523` for `af299e4c34f3eadd03efc61d4fc890e906a30e5a`
  completed successfully: migration upgrade, downgrade/re-upgrade, compilation and
  pytest all passed; **25 passed, 5 warnings**.
