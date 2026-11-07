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

## Accounts receivable and payable increment

The next accounting increment adds:
- Customer receivable invoices linked to tenant CRM contacts.
- Supplier payable bills linked to tenant procurement suppliers.
- Draft invoice headers and itemized lines with decimal quantity, unit price and
  tenant-entered tax rate/account. Amounts are rounded to two decimal places.
- Invoice posting creates a balanced general-ledger journal in the same database
  transaction and changes the invoice from draft to posted.
- Receipts and supplier payments create settlement journals, allocate against the
  invoice balance, prevent overpayment and use tenant-unique idempotency keys.
- Invoice ageing reports group unpaid balances into current, 1-30, 31-60, 61-90
  and over-90-day buckets.
- Invoice currency must match the organization's configured base currency; this
  slice does not implement foreign currency or revaluation.
- Branch-scoped members see only branch-visible invoices. Invoice creation and
  posting validate tenant ownership of counterparties and ledger accounts.
- UI at /accounting now includes draft invoice creation, posting, payments and
  ageing.

### Additional API

- POST /api/v1/accounting/invoices
- GET /api/v1/accounting/invoices
- POST /api/v1/accounting/invoices/{id}/post
- POST /api/v1/accounting/invoices/{id}/payments
- GET /api/v1/accounting/aging?invoice_type=receivable|payable&as_of=YYYY-MM-DD

The customer invoice posts debit receivables and credit revenue/output-tax accounts.
The supplier bill posts debit expense/input-tax accounts and credit payables.
Receivable settlement debits a cash/bank asset account and credits receivables;
payable settlement debits payables and credits cash/bank. The payment account must
be an asset account. Tax account types are validated by invoice direction.

### Important limitations

This is a general ledger subledger foundation, not a complete accounting package.
It does not yet provide supplier invoice three-way matching, purchase-order receipt
matching, credit notes, debit notes, refunds, invoice approval, recurring invoices,
customer statements, supplier statements, bank feeds, statement import/matching,
bank reconciliation, budgets, cost centres, fixed assets/depreciation, fiscal
periods, period close/lock, reversals, financial statements, cash-flow reporting,
multi-currency, tax compliance or statutory filing. Tenant tax rates are data
provided by the operator; they are not a determination of statutory tax treatment.
No live payment gateway, M-Pesa or KRA eTIMS integration is included.
