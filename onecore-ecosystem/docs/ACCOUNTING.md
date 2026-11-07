# Accounting foundation

This increment implements a tenant-scoped chart of accounts, posted double-entry
journals and a trial-balance report. It is the first accounting ledger slice, not a
complete statutory or production accounting package.

## API

- `GET /api/v1/accounting/accounts`
- `POST /api/v1/accounting/accounts`
- `POST /api/v1/accounting/journals`
- `GET /api/v1/accounting/journals`
- `GET /api/v1/accounting/trial-balance`

All endpoints require bearer authentication and active tenant membership. Account
codes are unique per organization. Account types are asset, liability, equity,
revenue and expense. Creating accounts requires manage permission; posting journals
requires create permission; reports require read permission. Branch-scoped
memberships can only see or post journals within their branch scope.

Journal posting validates that there are at least two lines, each line is either a
debit or a credit (never both or neither), and total debits equal total credits and
are greater than zero. The journal header and all lines are inserted in one database
transaction. Posted journals are read-only through the API. Each journal is assigned
a unique reference number and an audit event is recorded.

## UI

A basic accessible accounting interface is served at `/accounting`. It supports
sign-in, creating accounts, posting a two-line balanced journal and viewing the
trial balance. It does not yet provide journal reversals, draft/approval workflows,
multi-currency, period close or financial statement generation.

## Not yet delivered

- Accounts payable/receivable, invoices, supplier/customer subledgers and payment
  allocation.
- Bank/cash books, bank statement import, matching and reconciliation.
- Periods, fiscal-year controls, closing/locking, journal approval and reversals.
- Budgets, cost centres, fixed assets, depreciation and tax/statutory reports.
- Balance sheet, profit/loss, cash-flow and general-ledger drill-down reports.
- Opening balances and import/migration tools.
- Multi-currency revaluation, exchange gains/losses and consolidation.
- Full account/journal detail UI, pagination, filters, export and audit viewer.
- PostgreSQL concurrency, security, accessibility and UAT testing.

No KRA eTIMS, tax filing, payment processing or external accounting certification
is included in this slice.
