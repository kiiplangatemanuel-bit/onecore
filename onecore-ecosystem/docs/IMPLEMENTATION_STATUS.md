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


## School Management academic foundation (8 November 2026)

Implemented on `main`:

- Tenant-owned classes/streams by academic year and optional branch.
- Applicant admissions with unique tenant admission numbers, guardian contacts and
  controlled applicant-to-active admission transition.
- Tenant-owned subject catalogue to support CBC learning areas/subjects.
- Class/subject assessments with academic year, term, maximum score and weight.
- Batch mark entry/update, active class membership validation and score ceilings.
- Configurable grade bands with overlap prevention.
- Manage-permission publication locks marks; published assessment results provide
  grades and competition ranking with ties sharing rank.
- Weighted term report-card summary from published assessments.
- APIs under `/api/v1/school`; starter workspace at `/school`; migration
  `0007_school`; models/schemas/routes/UI/tests and `docs/SCHOOL.md`.
- Commits: `a36e135` (models), `a266c90` (schemas), `ef7c77e` (migration),
  `132be73` (APIs), `32af97b` (UI), `581f9e5` (UI route),
  `98e5b25` (assessment listing/report cards), `18547be` (tests),
  plus follow-up test and documentation commits.

School remains incomplete: no complete application review, guardian/teacher/staff
portals, attendance, timetable, full CBC strands/outcomes, moderation, year/term
promotion, advanced ranking configurations, approved report-card PDF/transcript,
fees/bursaries, boarding, transport, library, discipline, school health, e-learning,
communication, M-Pesa, statutory integrations, bilingual full UI, security/safeguarding
review, performance testing or UAT. The current grading and ranking functions are a
limited initial implementation, not a complete national CBC rules engine.


### School foundation CI verification

- GitHub Actions run `42363505011` for commit `4659fdcd35cb449ab02ae620017ed8dd7be536f3` completed successfully.
- Alembic migration upgrade, downgrade and re-upgrade passed; Python compilation passed; pytest reported **46 passed, 5 warnings**.
- Earlier school code run `42363477316` also passed with 46 tests. This is SQLite CI evidence only; no production PostgreSQL rehearsal, security/safeguarding review, browser accessibility audit or school pilot UAT has been completed.

## Accounting receivables/payables increment (8 November 2026)

Implemented on main:
- Customer AR invoices linked to tenant CRM contacts and supplier AP bills linked to
  tenant procurement suppliers.
- Draft invoices with itemized lines, quantities, two-decimal unit prices, tenant
  configured tax rates and tax ledger accounts.
- Invoice posting creates balanced double-entry journals and locks the invoice state.
- AR receipts and AP payments create settlement journals, enforce outstanding balance
  limits, and use tenant-unique idempotency keys.
- Invoice listing and ageing buckets (current, 1-30, 31-60, 61-90, over 90 days).
- Base-currency validation against organization configuration; foreign currency is
  intentionally not supported by this increment.
- Tenant/branch ownership validation and audit events.
- Accounting UI now includes invoice creation, posting, payments and ageing.
- Migration 0008_accounting_invoices; models, schemas, API, tests and updated
  docs/ACCOUNTING.md.

Remaining accounting work:
- Bank/cash statement import and reconciliation, bank feed integrations.
- Customer/supplier statements, credit/debit notes, refunds, invoice approval and
  recurring invoices.
- Three-way match between purchase orders, goods receipts and supplier invoices.
- Budgets, cost centres, fixed assets/depreciation, fiscal periods and close/lock.
- Reversals, balance sheet, P&L, cash-flow, GL drill-down and export/reporting.
- Foreign currency, exchange revaluation and consolidation.
- Statutory tax determination, eTIMS filing, provider/payment integrations.
- PostgreSQL production rehearsal, race testing, full security/accessibility review
  and UAT.

The increment has been committed, but do not mark it verified until GitHub Actions
completes migration upgrade/downgrade/re-upgrade, compilation and the complete pytest
suite. The SQLite CI environment is not a production database rehearsal.

### Accounting AR/AP CI verification

- GitHub Actions run 42364078944 for commit 29b47f0c85a5f3aec8e2942e5d8f3b2e7394ec07 passed.
- Alembic migration upgrade, downgrade and re-upgrade passed.
- Python compilation passed.
- Full pytest suite: 49 passed, 5 warnings.
- The migration/test run uses CI SQLite. It does not establish PostgreSQL production
  compatibility, race-safety under real concurrent payments, statutory tax correctness,
  security certification or production readiness.


### Accounting fiscal controls, budgets, fixed assets and statements (8 November 2026)

Implemented on main:
- Tenant fiscal periods with unique period codes, overlap prevention and close action.
  Journal posting, invoice posting/settlement and fixed-asset journals reject dates
  within a configured closed period. Closing blocks while draft invoices remain in
  that period.
- Period budgets with revenue/expense allocations, approval and actual-vs-budget
  report; branch-specific budget lines supported.
- Fixed asset register with acquisition journal, asset/salvage values, useful life and
  ledger account mapping.
- Monthly straight-line depreciation with per-asset/month uniqueness, idempotency,
  depreciation journals and stop-at-salvage calculation.
- Basic ledger-derived profit-and-loss and balance-sheet report.
- Migrations 0009_accounting_controls and 0010_accounting_depreciation.
- API, model, schema and tests added. Documentation updated in docs/ACCOUNTING.md.

Verified code commit 6e42ff69a5f2fd9f692dab30b8629bad82fb41b8:
GitHub Actions run 42364331566 passed migration upgrade, downgrade/re-upgrade,
Python compilation and pytest: 50 passed, 5 warnings. The run used the CI SQLite
environment, not production PostgreSQL.

Remaining accounting gaps include bank statements/import and reconciliation,
customer/supplier statements, credit/debit notes, refunds, recurring invoices,
procurement three-way matching, cost centres, monthly budgets/encumbrances, asset
disposal/revaluation/impairment, fiscal closing journals and retained-earnings
roll-forward, cash-flow statement, multi-currency, statutory tax/eTIMS, production
PostgreSQL rehearsal, concurrency/performance, finance UAT and security review.
Period boundaries are only enforced where an organization has configured periods.


### Accounting bank statement reconciliation increment (8 November 2026)

Implemented on main:
- Tenant-owned bank statement headers and imported statement lines.
- JSON statement import validates bank asset account, authorized branch, transaction
  date range, non-zero two-decimal movements and opening-plus-movements arithmetic.
- Manual one-to-one matching against posted journal lines for the same bank account,
  statement period, branch and exact signed amount.
- Reconciliation refuses unmatched statement lines and compares opening/closing
  statement balances with ledger balances before/through the statement period.
- Reconciled statements are locked against further line matching.
- Branch-scoped users must explicitly select an authorized branch.
- Accounting workspace includes statement import, match and reconcile controls.
- Migration 0011_accounting_bank_reconciliation; API/models/schemas/tests and
  documentation in docs/ACCOUNTING.md.

Verification: GitHub Actions run 42364648747 passed migration upgrade,
downgrade/re-upgrade, Python compilation and pytest: 51 passed, 5 warnings.
This is CI SQLite verification, not a live bank feed or production bank reconciliation
sign-off.

Remaining bank reconciliation gaps: CSV/XLSX statement parsing, direct bank feeds,
automatic/fuzzy matching, bank account verification, provider credentials, bank
charges workflow and finance-team UAT. No live bank integration is claimed.


## CRM quotes and pipeline forecast increment (8 November 2026)

Implemented on main:
- Tenant-owned sales quotes linked to customer contacts and optionally sales leads.
- Quote line items with quantity, price, tax rate and server-calculated totals.
- Draft -> issued -> accepted/rejected lifecycle with expiry handling and audit events.
- Branch alignment validation between quote, customer contact and linked lead.
- Quote currency constrained to the organization's configured base currency.
- Quote detail/list APIs and accessible CRM workspace controls.
- Pipeline forecast grouped by currency and lead stage using fixed, documented
  stage probability assumptions. This is a transparent heuristic, not a statistical
  forecast.
- Migration 0012_crm_quotes; models, schemas, APIs, UI, tests and docs/CRM.md.

Verification: GitHub Actions run 42364853288 passed migrations, downgrade/re-upgrade,
compilation and pytest: 53 passed, 5 warnings.

CRM remains incomplete: quote PDF generation, email/SMS delivery, customer signature,
quote-to-order conversion, contracts, campaigns, consent/preference management,
communication logs and provider delivery, segmentation, configurable stages and
probabilities, conversion cohort analytics, forecasting models, contact merge,
import/export, team assignment and UAT.


## School attendance increment (7 November 2026)

- Added `SchoolAttendance` tenant-owned records with branch/class/learner references,
  daily status, note and recorder attribution.
- Added validated batch register payload: `present|absent|late|excused` statuses and no
  duplicate learner IDs per request.
- Added `POST /api/v1/school/attendance` for create/correct and
  `GET /api/v1/school/attendance?class_id=...&attendance_date=...` for retrieval.
- Writes verify the class belongs to the active tenant and branch scope, and every
  learner is active and enrolled in that class. A learner cannot have two entries
  for the same tenant/date. Batch updates commit atomically and emit an audit event.
- Added reversible migration `0013_school_attendance` after `0012_crm_quotes`.
- Added schema, uniqueness, model and OpenAPI route tests; updated `docs/SCHOOL.md`.
- CI run for test commit `35d2262c137307fdf6fdfc1139a5d321e8ffcf7f` passed:
  dependencies, migration upgrade, downgrade/re-upgrade, compilation and pytest.
  Documentation/status follow-up run was still in progress at status update time.
- Follow-on gaps: guardian notifications, attendance analytics, timetable/period
  attendance, CSV import and production PostgreSQL concurrency/UAT. A basic staff
  attendance register UI was added at `/school` with class/date loading, status/note
  editing and batch save; its UI contract is covered by a test.



## Procurement requisitions increment (7 November 2026)

- Added tenant/branch-scoped requisition header and line models.
- Added draft requisition creation with product ownership checks, positive decimal
  quantities, unique product lines and required business justification.
- Added submit, approve and reject transitions. Only the requester may submit; a
  different organization manager must review; rejection requires a reason.
- Added organization/branch filters, row locking for state transitions and audit
  events for create, submit, approve and reject.
- Added reversible migration `0014_procurement_requisitions`.
- Added basic requisition controls to `/procurement` and updated
  `docs/PROCUREMENT.md`.
- Automated tests cover payload validation, duplicate product rejection, model
  registration and OpenAPI routes.
- CI status: awaiting GitHub Actions result for the increment's final commit.
- Remaining gaps: configurable approval tiers/amount thresholds, delegation,
  requisition-to-PO conversion, multi-line UI editing, attachments and full UAT.



## Procurement GRN inspection increment (7 November 2026)

- Existing requisition workflow retained: draft, submit, manager approve/reject,
  requester self-approval prevention, branch scope and audit events.
- Added GRN header/line models and reversible migration
  `0015_procurement_grn_inspection`.
- Goods delivery creates a `pending_inspection` GRN and reserves the PO delivered
  quantity. The old direct-to-inventory receipt endpoint now returns HTTP 410.
- Manager inspection must account for every delivered unit as accepted or rejected;
  rejection requires a reason. Accepted quantity alone posts to the inventory ledger
  with a stable per-GRN-line idempotency key.
- Added GRN list/detail/create/inspect APIs and procurement workspace forms.
- Added tests for schema validation, model/API registration, legacy endpoint
  deprecation and workspace controls.
- CI verification passed on commit `b541701e4fa3c509c2ffcca7cc2707c4e1a42b15`:
  migration upgrade and downgrade/re-upgrade, Python compilation, and `64 passed`
  pytest checks (5 dependency deprecation warnings). Follow-up documentation commit
  triggered a separate workflow run.
- Remaining gaps: supplier returns/credit notes, supplier invoices/three-way match,
  multi-level approval thresholds, RFQs, supplier performance and UAT.


## Procurement completion increment (7 November 2026)

- Approved requisitions can be converted into draft purchase orders with the original branch, product lines and quantities preserved; supplier and unit prices are selected at conversion, and duplicate conversion is blocked.
- RFQ creation supports supplier invitations, complete line-level quotations, tax-inclusive price comparison and quote award into a draft PO.
- Configurable sequential PO approval tiers support amount ranges, role-specific approvers, distinct approvers and creator self-approval prevention. Approval history is queryable; PO release occurs only after all applicable levels approve.
- Supplier invoice records perform three-way checks against PO supplier/currency/prices and inspected, accepted, non-returned GRN quantities. Duplicate invoice references are prevented by a unique database constraint.
- Supplier returns are restricted to accepted GRN quantities, cannot exceed available stock, write negative inventory ledger movements and retain credit-note references.
- Supplier performance endpoint reports PO/GRN counts, delivered/accepted quantity and acceptance percentage.
- Added migration 0016_procurement_completion, frontend forms, API schemas/routes, docs/PROCUREMENT.md and automated validation/OpenAPI/UI tests.
- GitHub Actions run 42372561387 passed: dependency installation, migration upgrade, migration downgrade/re-upgrade, Python compilation and 68 passed pytest checks (5 warnings).
- Explicit remaining integration work: matched supplier invoices are recorded but not posted to AP journals or paid; credit-note references are captured but not posted to AP; no external supplier portal/email delivery, approval delegation/escalation, supplier statement reconciliation, or end-to-end production UAT yet.


## Accounting counterparty statements increment (in review)

- Added tenant- and branch-scoped customer and supplier statement API.
- Statements aggregate posted, partially paid and paid invoices with recorded
  invoice settlements; opening balances include pre-period activity and the
  response provides dated transactions and closing balance.
- Draft invoices are excluded; customer contacts and suppliers are resolved only
  inside the active organization.
- Added API contract test and updated docs/ACCOUNTING.md.
- Branch: feature/accounting-counterparty-statements.
- Verification is pending GitHub Actions. This increment does not yet provide
  statement PDF/export/email delivery or an accounting workspace UI.


## Accounting approvals and credit notes increment (CI passed)

- Added invoice approval submission, decision history and submitter self-approval
  prevention. Posting is blocked for invoices with pending or rejected approvals.
- Added tenant/branch-scoped receivable and payable credit notes with line quantity
  limits, proportional tax reversal, balanced ledger journal, unique tenant
  idempotency keys and fiscal-period checks.
- Invoice balances are reduced when credit notes post; customer/supplier statements
  now show original invoice gross value and separate negative credit-note movements.
- Added migration 0017, request validation, API contract tests and Accounting docs.
- Explicitly not included: customer refunds, supplier credit balances, multi-level
  Accounting approvals, credit note PDF/email delivery and approval dashboard UI.
- Branch: feature/accounting-credit-notes-approvals.
- GitHub Actions run `42373824056` passed migration upgrade, downgrade/re-upgrade,
  Python compilation and pytest at commit `3f3083b25fc7a9d8d16e60a967921e493060d474`.


## Accounting fiscal period close controls increment (CI pending)

- Added a read-only pre-close checklist endpoint reporting draft invoices,
  pending invoice approvals, draft credit notes, draft journals, unreconciled
  overlapping bank statements and unbalanced posted journals.
- Fiscal period close now returns structured blocker codes/counts and refuses
  closure until all detected blockers are resolved.
- Added API contract coverage and documented the endpoint and its boundaries.
- No schema migration is required for this logic-only increment.
- Branch: feature/accounting-fiscal-close-controls.
- Verification pending GitHub Actions migration upgrade/downgrade/re-upgrade,
  Python compilation and pytest.
- Not yet included: retained earnings transfer, subledger reconciliation,
  statutory/tax close validation, depreciation certification and sign-off pack.


## POS receipts and controlled returns increment (7 November 2026)

Implemented on branch `feature/pos-returns-refunds`:

- Tenant/branch-scoped sale receipt lookup with original sale lines, recorded tenders
  and per-line remaining returnable quantity.
- Manager-permission-gated partial/full return endpoint; returns are restricted to
  lines from the original posted sale and cannot exceed remaining sold quantities.
- Refund allocations must equal the return value and are capped by remaining recorded
  original tender by method; unsettled credit tenders are excluded.
- Returned stock is reintroduced through append-only inventory receipt movements in
  the original branch.
- Tenant-unique return idempotency keys, canonical request hashes, conflict handling
  and audit events.
- Models: `POSReturn`, `POSReturnLine`, `POSRefund`; migration
  `0018_pos_returns`; service validation and contract/route tests.
- APIs: `GET /api/v1/pos/sales/{sale_id}` and
  `POST /api/v1/pos/sales/{sale_id}/returns`.

Boundaries: refund records do not execute cash/card/bank/M-Pesa payouts; no provider
refund adapter is enabled. Return value uses original stored sale prices; discount
and tax allocation and accounting journal integration remain outstanding. The UI
receipt/return workflow is being added in this increment and must be verified before
the slice is called complete. CI must pass migration upgrade, downgrade/re-upgrade,
compilation and pytest before merge.


## School learner promotion and transfer history increment

- Added append-only learner placement history and controlled promotion/transfer API.
- Promotion must advance to a later academic year; transfer may move to a parallel
  class or later year but cannot move backwards.
- Requires organization manage permission and access to both source and target
  branches; learner update, history record and audit event are committed together.
- Added history retrieval with tenant and branch checks, schema/model/OpenAPI tests,
  a placement form/history viewer in the School workspace, and documentation.
- Migration: `0019_school_learner_placements`.
- Branch: `feature/school-learner-promotions`.
- Pending CI: migration upgrade/downgrade/re-upgrade, compilation and pytest.
- Not included: bulk promotion, capacity/waitlists, guardian consent, eligibility
  rules, fee carry-forward, transcript migration or guardian notifications.



## CRM accepted quote to sales order increment (7 November 2026)

Implemented on branch `feature/crm-sales-order-conversion`:

- Convert only accepted, unexpired tenant quotes into confirmed sales orders.
- One order per source quote; repeat conversion is idempotent and returns the existing order.
- Snapshot quote lines, quantities, prices, tax rates and calculated totals.
- Tenant/branch-scoped conversion, listing and detail APIs with audit events.
- Migration `0020_crm_sales_orders`; tests cover conversion request validation,
  model registration and API route contracts.

Boundaries: sales orders do not reserve/deduct stock, generate invoices, collect deposits,
dispatch or notify customers. CI and reviewer acceptance are required before merge.



## CRM marketing consent and campaign preparation increment (7 November 2026)

Implemented on branch `feature/crm-consent-campaigns` (based on CRM sales order branch):

- Append-only channel-specific marketing consent grants/revocations with source,
  actor, timestamps and optional expiry.
- Draft email/SMS/WhatsApp campaign creation and manager-only recipient preparation.
- Recipient selection uses the latest consent decision, excludes expired/revoked
  consent and contacts without a usable channel address.
- Tenant/branch filters, address snapshots, unique campaign-contact constraint and
  idempotent ready state.
- Migration `0021_crm_consent_campaigns`, APIs, tests and documentation.

Boundaries: campaign preparation does not send messages. Provider delivery, callbacks,
unsubscribe webhooks, suppression lists, scheduling and delivery analytics remain
unimplemented. A dispatch worker must re-check current consent immediately before send.



## HR employee directory and leave workflow increment (7 November 2026)

Implemented on branch `feature/hr-employees-leave` (based on CRM campaign branch):

- Tenant/branch-scoped employee directory with organization-unique employee numbers,
  optional linked organization users, contact details, department, role and employment type.
- Employee self-service leave request when employee profile is linked to the signed-in user;
  HR managers can also submit on behalf of staff.
- Leave types: annual, sick, compassionate, unpaid, parental and other.
- Working days calculated inclusively excluding weekends; overlapping pending or
  approved requests are rejected.
- HR managers can review and approve/reject pending requests; employees cannot decide
  their own leave. Sensitive changes create audit events.
- Migration `0022_hr_employee_leave`, HR APIs, starter workspace and tests.

Boundaries: no leave entitlements/accrual ledger, holiday calendar, balance deduction,
payroll, payslips, statutory deductions, attendance integration or employee document
management. Public holidays are not excluded from the current working-day calculation.


## HR attendance and timekeeping increment (7 November 2026)

Implemented on branch `feature/hr-attendance-timekeeping`:

- Server-timestamped clock-in/clock-out for the active employee profile linked to
  the signed-in user; employee self-service is tenant and branch scoped.
- One attendance session per employee per UTC calendar day, protected by a unique
  database index and explicit conflict responses for duplicate punches.
- Clock-out calculates elapsed whole minutes; attendance rows retain UTC timestamps.
- Employee attendance history and manager team report with branch scope filtering.
- Audit events for clock-in and clock-out; migration `0023_hr_attendance`.
- Added accessible attendance controls and tables to the HR workspace plus contract
  and duration tests.

Boundaries: no organization timezone configuration, shift calendars, breaks, overtime,
geolocation/biometrics, offline punches, manager correction workflow, multiple daily
sessions or payroll integration. UTC-day attendance is not a local payroll timesheet.


## HR payroll preparation and approval increment (7 November 2026)

Implemented on branch `feature/hr-payroll-runs`, stacked on HR employee/leave and
attendance work:

- Added effective-dated employee payroll profiles with tenant/branch scope and
  overlap rejection. Base pay is explicitly the amount for one complete pay period.
- Added draft payroll runs that include active eligible employees with exactly one
  profile covering the full period; mixed-currency and overlapping periods are
  rejected.
- Added one-time earning/deduction items with decimal arithmetic, tenant-unique
  idempotency keys and canonical request hashes.
- Gross, deductions and net totals are recalculated from the base period pay and
  explicit items; deductions greater than gross are rejected.
- Added manager approval with creator self-approval prevention and immutable
  approved run snapshots.
- Added employee self-service retrieval of approved payslips and a basic HR payroll
  workspace.
- Added migration `0024_hr_payroll`, payroll schemas/services, tests and HR docs.

Boundaries: no PAYE, NSSF, SHIF, housing levy, pension, benefits tax, reliefs,
overtime premium, leave-pay or employer-contribution engine; no bank/M-Pesa payout,
payslip PDF/email, payroll journal or accounting posting. Payroll figures are
operator-entered and are not a statutory calculation or payment instruction.
CI and professional jurisdiction-specific validation are required before any
operational payroll use.


## School fee schedules, learner billing and receipts increment (7 November 2026)

Implemented on branch `feature/school-fees-payments`:

- Class/year/term fee schedules with tenant and branch scope, currency and due date.
- Manager-controlled bulk billing of active learners in a class; unique learner/schedule
  constraints make repeated billing safe and non-duplicating.
- Learner fee account with charge, paid and outstanding balances plus receipt history.
- Manual payment receipt capture with tenant-unique receipt numbers and charge
  allocations; allocations must equal receipt total, match currency and not overpay.
- Payment, allocations and charge balance updates commit atomically with audit events.
- Four school fee models, migration `0024_school_fees`, APIs, starter UI, docs and
  schema/model/OpenAPI tests.

Boundaries: no guardian portal, bursary/discount workflows, payment plan, refund or
reversal process, M-Pesa/bank/card provider verification, payment settlement,
accounting journal integration or UAT. Tender methods are manually recorded only.


## Healthcare patient directory and appointments increment (7 November 2026)

Implemented on branch `feature/healthcare-patients-appointments`:

- Tenant/branch-scoped patient registration with organization-unique patient numbers.
- Minimal patient demographics and emergency contact fields; no clinical diagnosis,
  medication or treatment records are introduced in this slice.
- Tenant/branch-scoped appointment scheduling, optional provider assignment to an
  active organization member, and provider overlap prevention.
- Appointment lifecycle transitions from scheduled to cancelled or completed,
  with manager permission and audit events.
- Migration `0025_healthcare_patients_appointments`, APIs, starter workspace,
  tests and module documentation.

Boundaries: no clinical encounter notes, diagnoses, prescriptions, allergies, lab,
imaging, pharmacy, admission/bed management, insurance, billing, consent workflows,
patient portal, clinical audit certification, interoperability or UAT. Sensitive
healthcare data requires a jurisdiction-specific privacy/security review before
production use.
