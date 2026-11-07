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


## Fiscal periods, budgets, fixed assets and statements

A further increment adds:
- Tenant fiscal period records with unique codes, non-overlapping date ranges and
  open/closed status. Closing requires all draft invoices dated in the period to be
  posted or otherwise resolved. New journals and invoice/payment/asset/depreciation
  journals are rejected when their accounting date is in a closed period.
- Period budgets with revenue/expense account allocations, approval and actual-vs-
  budget reporting. Budgets are tenant-owned; branch-level budget lines are supported.
- Fixed asset acquisition records with asset, accumulated depreciation, depreciation
  expense and payment ledger accounts. Acquisition creates a balanced journal.
- Monthly straight-line depreciation with per-asset/per-month uniqueness, an
  idempotency key and a journal entry. Depreciation stops at salvage value.
- A period profit-and-loss and as-at balance-sheet report derived from posted journal
  lines. It reports whether the balance sheet equation balances.

### Additional API

- GET/POST /api/v1/accounting/fiscal-periods
- POST /api/v1/accounting/fiscal-periods/{id}/close
- POST /api/v1/accounting/budgets
- POST /api/v1/accounting/budgets/{id}/approve
- GET /api/v1/accounting/budgets/{id}/performance
- GET/POST /api/v1/accounting/fixed-assets
- POST /api/v1/accounting/fixed-assets/{id}/depreciation
- GET /api/v1/accounting/financial-statements?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

### Limitations and operational controls

- Period enforcement applies to dates covered by configured, closed periods. An
  organization that has not configured fiscal periods has no fiscal-period boundary
  enforcement; configure periods before relying on period-close controls.
- Budgeting is period-level, not monthly/departmental forecasting; cost centres,
  commitments and purchase-order encumbrances are not implemented.
- Fixed assets use straight-line monthly depreciation only. Disposal, revaluation,
  impairment, component accounting, asset transfers and tax depreciation are not
  implemented.
- Financial statements are basic ledger-derived summaries. Opening balances,
  retained-earnings close journals, cash-flow statement, statutory presentation,
  consolidation, audit sign-off and export formats remain outstanding.
- The financial statement and budget reports require PostgreSQL scale/performance
  testing and finance-team reconciliation before operational use.


## Bank statement import and reconciliation increment

- Tenant bank statement import accepts dated signed transaction lines, statement
  reference, opening and closing balances and a bank asset ledger account.
- Import validates statement date ranges and arithmetic (opening balance plus
  movements equals closing balance).
- Each imported line can be matched to one posted general-ledger journal line for
  the same bank account, period and branch. Amounts must agree exactly using the
  ledger debit-minus-credit sign convention.
- A ledger line can only be matched once. A statement cannot be reconciled while
  unmatched lines remain.
- Reconciliation compares the statement opening and closing balances to the
  corresponding ledger balances; only then is the statement marked reconciled.
- Branch-scoped users must import statements for an explicitly authorized branch.
- A basic import/match/reconcile interface is available in the accounting workspace.

### Additional API

- POST /api/v1/accounting/bank-statements
- GET /api/v1/accounting/bank-statements
- GET /api/v1/accounting/bank-statements/{id}
- POST /api/v1/accounting/bank-statements/{id}/match
- POST /api/v1/accounting/bank-statements/{id}/reconcile

This increment provides a structured JSON import contract. It does not include
bank-provider APIs, direct bank feeds, automatic fuzzy matching, CSV/XLSX upload,
statement file parsing, bank account verification or live bank connectivity.
Unmatched bank charges/fees must first be entered into the ledger before the
statement can reconcile. Manual match workflows require finance operator review.


## Customer and supplier statements

The counterparty statement endpoint builds a chronological statement from posted,
partially paid and paid invoices plus their recorded settlements. It is scoped to
the active organization and branch permissions. Draft invoices are excluded.
Opening balance includes posted activity before the requested start date; the
transaction list includes activity inside the requested date range.

- GET /api/v1/accounting/statements/customer/{contact_id}?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
- GET /api/v1/accounting/statements/supplier/{supplier_id}?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

The response includes counterparty identity, currency, opening balance, dated
invoice/payment transactions and closing balance. This is a ledger-subledger
statement, not a PDF/email delivery or external customer portal. It currently
uses the organization's base currency when there are no invoices in the period.


## Invoice approval and credit note increment

- A draft invoice can be submitted for approval. The submitter cannot approve their
  own invoice; an organization manager/admin with manage permission records an
  explicit approval or rejection and a decision note.
- Posting is blocked when an approval record exists and is not approved. Existing
  invoices with no approval record retain the legacy direct-post path for backward
  compatibility; organizations should enforce approval operationally for new invoices.
- Credit notes are posted against an existing posted receivable/payable invoice.
  Each credit note references invoice lines and quantities, calculates proportional
  net and tax amounts from the original invoice line, and creates a balanced reversal
  journal using the same revenue/expense, tax and AR/AP control accounts.
- Credited quantities cannot exceed original invoice-line quantities after previous
  posted credit notes. Credit note number and idempotency key are unique per tenant.
- Credit notes cannot exceed the invoice's currently outstanding balance. Customer
  refunds and supplier credit balances are not implemented in this increment.
- Posting a credit note reduces the invoice's remaining subtotal, tax and total;
  posted credit notes are included as separate negative movements in customer and
  supplier statements so the statement preserves the original invoice and credit
  history.
- Credit-note dates are rejected when they fall inside a configured closed fiscal
  period. Credit notes are branch-scoped and audited.

### Additional API

- POST /api/v1/accounting/invoices/{id}/submit-for-approval
- GET /api/v1/accounting/invoices/{id}/approval
- POST /api/v1/accounting/invoices/{id}/approval-decision
- POST /api/v1/accounting/invoices/{id}/credit-notes
- GET /api/v1/accounting/credit-notes?invoice_id={id}

This increment adds approval and credit-note persistence in migration
0017_accounting_approvals_credit_notes. It does not yet include multi-level
accounting approvals, PDF/email credit-note delivery, a dedicated approval
dashboard, or refund/disbursement processing.


## Fiscal period close controls

The close-check endpoint provides a pre-close checklist for a configured period.
It reports counts for draft invoices, pending invoice approvals, draft credit
notes, draft journals, unreconciled bank statements overlapping the period, and
posted journals whose debit and credit totals do not balance.

- GET /api/v1/accounting/fiscal-periods/{id}/close-check
- POST /api/v1/accounting/fiscal-periods/{id}/close

The close action now refuses to lock a period while any checklist blocker remains
and returns machine-readable blocker codes and counts. Resolve the reported work,
re-run the checklist, and close only when ready_to_close is true. The endpoint is
read-only and does not create or alter accounting entries.

This is an operational close checklist, not a complete statutory close process:
it does not yet perform retained-earnings transfer, tax filing validation,
subledger-to-control-account reconciliation, depreciation completeness
certification, management sign-off or a formal close pack.


## AR/AP subledger-to-control-account reconciliation

- Added a read-only, tenant- and branch-scoped reconciliation for receivables and
  payables at a selected accounting date.
- The subledger side includes posted invoices dated on or before the cutoff, less
  settlements and posted credit notes dated on or before that date.
- The general-ledger side sums posted journal lines on the invoice control accounts
  through the same cutoff, using the normal debit balance for receivables and credit
  balance for payables.
- The response reports each control account's subledger balance, GL balance,
  difference and balanced flag, plus totals and an overall balanced result.
- API: GET /api/v1/accounting/subledger-reconciliation?invoice_type=receivable|payable&as_of=YYYY-MM-DD

This is a diagnostic comparison, not an automatic adjustment or journal-posting
workflow. Differences must be investigated and corrected through authorized source
transactions. It does not certify tax, statutory or audit compliance. Historical
cutoff results rely on dated invoice, payment and credit-note records; imported
opening balances or unlinked manual control-account entries may produce differences.


## General-ledger financial statements

- Added a tenant- and branch-scoped financial statement endpoint:
  `GET /api/v1/accounting/financial-statements`.
- `statement_type=income_statement` requires `start_date` and supports an
  optional `end_date`; revenue and expense balances include posted journals in
  that date range.
- `statement_type=balance_sheet` reports asset, liability and equity balances
  cumulatively through `end_date`.
- Account balances use normal debit/credit conventions. The response includes
  account-level totals, revenue, expenses, net income, assets, liabilities, equity,
  current-period earnings and an accounting-equation difference.
- Reports use posted general-ledger journals only. Draft journals and operational
  subledgers that have not been posted are excluded.
- The balance sheet includes current-period net income alongside recorded equity;
  it does not post a retained-earnings transfer or close revenue/expense accounts.
  The balanced flag is a ledger arithmetic check, not an audit opinion or statutory
  statement certification.
- Currency is the organization's configured base currency; this report does not
  perform multi-currency translation or consolidation.


## Reviewed fiscal year-end close

- Added a read-only preview for a selected open fiscal period and an active
  organization-owned retained-earnings equity account.
- The preview totals posted revenue and expense account balances over the fiscal
  period, calculates net income, and displays the debit/credit lines required to
  close nominal accounts into retained earnings.
- Posting requires organization-wide accounting access, manage permission, a clean
  fiscal-period close checklist, a balanced close calculation and an exact
  confirmation-code match to the fiscal period code.
- The posting endpoint creates one immutable posted closing journal (when there
  are nominal balances) and marks the fiscal period closed in the same database
  transaction. A stable period reference prevents duplicate close journals.
- API:
  - GET /api/v1/accounting/fiscal-periods/{id}/year-end-close-preview?retained_earnings_account_id={id}
  - POST /api/v1/accounting/fiscal-periods/{id}/year-end-close
- The operation does not calculate tax, dividends, statutory reserves, prior-period
  restatements, foreign-currency translation or consolidated group adjustments.
  Finance must verify the chart-of-accounts mapping and preview before confirmation.
  A close journal and period lock are consequential accounting actions; production
  use requires database transaction, permissions, audit and finance UAT verification.


## General-ledger financial statements

- Added a tenant- and branch-scoped financial statement endpoint:
  `GET /api/v1/accounting/financial-statements`.
- `statement_type=income_statement` requires `start_date` and supports an
  optional `end_date`; revenue and expense balances include posted journals in
  that date range.
- `statement_type=balance_sheet` reports asset, liability and equity balances
  cumulatively through `end_date`.
- Account balances use normal debit/credit conventions. The response includes
  account-level totals, revenue, expenses, net income, assets, liabilities, equity,
  current-period earnings and an accounting-equation difference.
- Reports use posted general-ledger journals only. Draft journals and operational
  subledgers that have not been posted are excluded.
- The balance sheet includes current-period net income alongside recorded equity;
  it does not post a retained-earnings transfer or close revenue/expense accounts.
  The balanced flag is a ledger arithmetic check, not an audit opinion or statutory
  statement certification.
- Currency is the organization's configured base currency; this report does not
  perform multi-currency translation or consolidation.


## Extended AP, VAT reporting, cash flow and customer refunds

- A three-way-matched Procurement supplier invoice can be linked to a draft
  Accounting AP invoice using `POST /api/v1/procurement/supplier-invoices/{id}/post-to-accounting`.
  The link is one-to-one and retry-safe. The resulting AP invoice remains subject
  to accounting approval and normal posting controls.
- `GET /api/v1/accounting/statutory-tax-summary` reports posted sales and purchase
  tax by rate, less posted credit notes, with output/input and net VAT grouped by
  currency. It is a management report, not an eTIMS/KRA filing or tax certificate.
- `GET /api/v1/accounting/cash-flow` classifies posted cash-equivalent movements
  using chart-of-account cash-flow categories (operating, investing, financing).
  Configure bank/cash accounts as cash equivalents and counterpart accounts
  with the relevant activity category. Unclassified movements are explicitly shown.
- `POST /api/v1/accounting/invoices/{id}/refunds` settles only a customer credit
  balance created by posted credit notes. It requires an active asset cash/bank
  account, uses an idempotency key, posts a balanced journal and reduces the
  invoice's paid amount. Refunds cannot exceed the refundable credit balance.
- Fiscal close checks now block on matched Procurement supplier invoices that
  have not yet been converted into the accounting AP subledger.

## Configuration and compliance boundaries

VAT rates and tax accounts remain organization-configured. The summary does not
determine legal tax treatment, submit returns, create eTIMS receipts, or certify
statutory compliance. Cash-flow classifications are user-configured and must be
reviewed by the organization's finance team. Multi-currency consolidation and
foreign-exchange revaluation are not performed; the current invoice ledger requires
the organization base currency.
