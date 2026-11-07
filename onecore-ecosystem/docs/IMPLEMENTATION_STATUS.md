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


## Accounting ledger foundation (7 November 2026)

Implemented on `main`:

- Tenant-scoped chart of accounts with unique account codes per organization and
  account types asset/liability/equity/revenue/expense.
- Double-entry journal header and line models with decimal KES precision, branch
  references and immutable posted state at the API boundary.
- Journal posting validates at least two lines, exactly one debit or credit per line,
  positive totals and exact debit/credit equality; header and lines commit atomically.
- Tenant/branch authorization for account, journal and trial-balance endpoints.
- Audit events for account creation and journal posting.
- APIs: GET/POST `/api/v1/accounting/accounts`, POST/GET
  `/api/v1/accounting/journals`, GET `/api/v1/accounting/trial-balance`.
- Basic accessible UI at `/accounting`; migration `0003_accounting`;
  domain service `app/services/accounting.py`; tests in `tests/test_accounting.py`;
  operator/domain notes in `docs/ACCOUNTING.md`.
- Key commits: `c803b1b` (models), `0c42192` (schemas), `4ec214f`
  (journal rules), `3ecde60` (API), `61ec668` (migration), `293a67b` (tests),
  `effd19b` (UI), `b1a8fb0` (UI route), `fc59ecb` (documentation).

Accounting remains incomplete: AP/AR, invoicing and subledgers, cash/bank books and
reconciliation, fiscal periods/close, approvals and reversals, budgets, cost centres,
assets/depreciation, statutory tax, financial statements, multi-currency, consolidation,
opening balance imports, full reporting UI, security/performance/UAT testing.

CI for this increment must complete migration upgrade/downgrade/re-upgrade,
compilation and pytest before this accounting slice is considered verified. Do not
claim production readiness or statutory compliance.


## CRM contacts and pipeline vertical slice (7 November 2026)

Implemented on `main`:

- Tenant-owned contacts with email/phone duplicate checks and optional branch ownership.
- Sales leads with source, stage, value/currency, assigned active tenant member and
  next step; tenant/branch-scoped list and updates.
- Controlled sales-stage transitions in `app/services/crm.py`.
- Activities (call/email/meeting/task/note) linked to exactly one tenant contact or
  lead; due date, completion and audit history.
- Branch authorization enforced when creating leads/activities and listing/completing
  activities; tenant isolation applied to all CRM lookups.
- APIs under `/api/v1/crm`; accessible starter UI at `/crm`.
- Migration `0004_crm`; tests in `tests/test_crm.py`; docs in `docs/CRM.md`.
- Key commits: `ded9f53` (models), `02a18d3` (schemas), `964fbbc` (pipeline rules),
  `b69a228` (CRM APIs), `5ddea53` (migration), `027a93a` and `36d515c`
  (branch-scope hardening), `15162ed` (UI), `d9cb749` (route), `6d8499e` (tests).

CRM still incomplete: quoting/proposals/contracts, sales order conversion, marketing
campaigns and consent, communications delivery, pipeline forecasting/analytics,
contact merge/edit/archive, full activity calendar/reminders, role/team ownership,
import/export, PostgreSQL concurrency, end-to-end branch isolation, security,
accessibility and UAT.

CI must verify migration upgrade/downgrade/re-upgrade, compile and full pytest before
this CRM increment is considered verified.


## Procurement vertical slice (7 November 2026)

Implemented on `main`:

- Tenant-owned supplier directory.
- Purchase orders with supplier, branch, currency, product lines, quantities and
  decimal unit costs.
- Draft -> approved -> partially_received/received lifecycle. Approval requires
  organization manage permission.
- Goods receipt validates approved state, tenant-owned PO lines, branch scope,
  positive quantities and remaining order quantity.
- Receipt writes append-only inventory receipt movements with per-tenant idempotency;
  duplicate replay does not add stock a second time.
- Audit events for supplier creation, PO creation/approval and goods receipt.
- APIs: GET/POST `/api/v1/procurement/suppliers`, GET/POST
  `/api/v1/procurement/orders`, POST `/api/v1/procurement/orders/{id}/approve`
  and POST `/api/v1/procurement/orders/{id}/receive`.
- Migration `0005_procurement`; tests in `tests/test_procurement.py`; domain
  documentation in `docs/PROCUREMENT.md`.
- Key commits: `bfa6a4d` (models), `8246918` (schemas), `c90d9bf` (API),
  `10f90c6` (migration), `183c658` (tests), `ce2315f` (documentation).

Procurement gaps: supplier edit/archive, requisitions, RFQ and quote comparison,
configurable multi-level approval matrix, PO editing/cancellation/dispatch, GRN
inspection and returns, supplier invoice matching, landed-cost allocation, AP
integration, procurement UI/reporting, PostgreSQL concurrent receipt tests,
security/accessibility and UAT.


- Basic accessible procurement UI served at `/procurement` for supplier creation,
  purchase-order creation, approval and goods receipt; PO detail API supports the UI.
- Additional UI/detail commits: `2721c7c` (authorized PO detail), `9fce237`
  (procurement UI), `fa0aff4` (UI route), `8704248` (route test),
  `e7e7633` (tracker).


## POS checkout and offline synchronization foundation (7 November 2026)

Implemented on `main`:

- Product catalogue sale price field and tenant product price returned by inventory API.
- Cashier shift open/current/close APIs with opening float, counted close cash and
  cash variance report.
- Branch-scoped POS catalogue with current stock snapshot.
- POS checkout sync validates cashier-owned open shift, branch access, product
  ownership, server-side catalogue price, stock availability and payment allocation.
- Sale header/lines/payment tenders and stock issue ledger entries commit atomically.
- Tenant-unique client transaction ID and canonical request hash ensure exact replay
  idempotency and reject conflicting reuse.
- Browser POS shell/service worker, AES-GCM encrypted IndexedDB queue/catalogue and
  online/manual retry; queue is synced through `POST /api/v1/pos/sync`.
- Migration `0006_pos`; service `app/services/pos.py`; tests in
  `tests/test_pos.py`; docs in `docs/POS.md`; UI at `/pos`.
- Key commits: `9e0f9ba` (models), `4208c34` (sale price), `2a5f705`
  (contracts), `34f24aa` (migration), `47d0dc5` (sync rules), `ac75d7e`
  (API), `9a7c1a7` (bounded idempotency), `9f56751` (current shift),
  `fdee128` and `a5850bf` (tests), `350a8c5` (POS UI), `cce35ed`
  (service worker), `0635170` (serve PWA), `953250a` (inventory sale-price UI).

POS remains incomplete: no offline sign-in after page reload, no 24-hour device
entitlement, single-line cashier UI, no refunds/discounts/tax/receipt printer/cash
drawer, no payment gateway verification, no stale stock reservation or supervisor
conflict review, no background sync telemetry/device management and no end-to-end
browser/device security/UAT. Credit is recorded as unsettled; card/bank tender records
are not provider verification.

Verified earlier completed runs before POS changes: CRM run `42362416897` passed
35 tests; procurement run `42362626229` passed 39 tests. POS migration, code and
new tests require a fresh CI run before they can be marked verified.


### Verified CI for Accounting, CRM, Procurement and POS foundations

- Accounting migration/code run `42362261548` passed; pytest: **30 passed, 5 warnings**.
- CRM code run `42362416897` passed; pytest: **35 passed, 5 warnings**.
- Procurement code run `42362626229` passed; pytest: **39 passed, 5 warnings**.
- POS plus current platform code run `42362993129` completed successfully; database
  migration upgrade, downgrade/re-upgrade and Python compilation passed; pytest:
  **43 passed, 5 warnings**.
- This verifies the current automated suite and migration chain in the CI SQLite
  environment only. It is not evidence of PostgreSQL production rehearsal, race/load
  testing, external provider certification, production deployment, penetration test
  or user acceptance approval.
