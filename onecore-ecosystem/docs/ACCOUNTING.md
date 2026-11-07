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


## Accounting completion: cash flow, tax workpapers, procurement AP and refunds

### Cash-flow reporting

- `GET /api/v1/accounting/cash-flow?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&cash_account_ids=1&cash_account_ids=2`
- Requires one or more tenant-owned asset accounts representing cash/bank.
- Uses posted journal lines only, calculates opening cash balance, operating/investing/financing movements, unclassified movement, net change and closing balance.
- Journal counterpart account types drive classification; multi-category journals are allocated proportionally. Review the method note in the response before relying on classifications. This is a ledger-derived management report, not a cash forecast or an IAS 7 certified statement.

### Statutory tax workpaper

- `GET /api/v1/accounting/statutory-tax-summary?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&tax_account_ids=10&tax_account_ids=11`
- Requires explicitly selected tenant-owned tax ledger accounts: liability accounts are treated as output tax and asset accounts as input tax.
- Returns account-level debit/credit movement, output tax, input tax and net tax payable.
- This is a reconciliation workpaper only. It does not determine Kenyan tax treatment, validate tax invoices, calculate statutory liabilities, file returns, connect to KRA eTIMS or provide statutory certification. Tax account mappings and rates remain configured and reviewed by the organization.

### Procurement-to-AP integration

- `POST /api/v1/accounting/procurement-invoices/{supplier_invoice_id}/integrate`
- Accepts a due date, AP liability control account, optional input-tax asset account and an explicit expense/asset ledger mapping for every matched procurement invoice line.
- Only three-way-matched supplier invoices are eligible. The integration creates one draft payable invoice and a durable unique source-to-ledger link; retries return the existing linked invoice.
- A pending maker-checker invoice approval is created automatically. A different authorized manager must approve it before the existing invoice posting endpoint will post the AP journal.
- The source procurement invoice is marked `accounted` after the bridge record and AP draft commit. AP settlement then uses the existing invoice payment endpoint and idempotency controls.
- Procurement invoice currency must match the organization's accounting base currency. Tax is allocated proportionally across source lines; the final line absorbs rounding.

### Credit-note refunds

- `POST /api/v1/accounting/credit-notes/{credit_note_id}/refund`
- `GET /api/v1/accounting/refunds?invoice_id={id}`
- Supports customer cash refunds (AR credit note) and supplier refund receipts (AP credit note), against a posted credit note.
- Refund amount is capped by the remaining credit-note amount and the amount previously settled against the invoice. The selected cash/bank account must be a tenant asset account.
- A balanced journal, refund record, idempotency key and audit event are committed together. The invoice's settled amount is reduced by the refund.
- No cash drawer, bank, card or M-Pesa payout/collection provider is called. The journal records the accounting event; external cash execution must be confirmed separately.

### Expanded close blocker

The fiscal-period close checklist now also blocks while a matched procurement supplier invoice dated in the period remains unintegrated into AP. Integrating the invoice changes its source status to `accounted`; it must still pass invoice approval and posting before it can be settled.

### Boundaries

These additions improve the accounting workflow but do not establish statutory compliance or production readiness. Remaining work includes jurisdiction-specific tax determination and KRA eTIMS certification, external payment execution, PostgreSQL production rehearsal, concurrency testing, finance/audit review, formal sign-off and user acceptance testing. Cash-flow classifications are heuristic based on general-ledger account types, and no future cash-flow forecasting model is included.


### Reviewed fiscal year-end close

- `GET /api/v1/accounting/fiscal-periods/{period_id}/year-end-close-preview?retained_earnings_account_id={id}`
- `POST /api/v1/accounting/fiscal-periods/{period_id}/year-end-close`
- Preview derives revenue and expense balances from posted general-ledger lines inside the selected open period and calculates a balanced nominal-account closing journal to an active equity retained-earnings account.
- The preview includes the full fiscal-period close checklist. The close action refuses unresolved blockers, requires organization-wide branch access, requires the exact period code as confirmation, and posts the closing journal and closes the period in one database transaction.
- A stable period-specific journal reference prevents duplicate closing journals. A period with no nominal-account activity can be closed without creating an empty journal.
- This is an operational accounting close control. It does not calculate tax provisions, statutory reserves, dividends, foreign-exchange translation, consolidation, prior-period restatements or auditor certification. Finance/audit approval and statutory review remain required.


## POS automatic journal integration

POS checkout and returns now feed the general ledger through an idempotent source bridge. Organizations configure one tenant-level account mapping for cash, card clearing, bank clearing, credit receivables, sales revenue, sales discounts, output tax and sales returns.

For each posted POS sale:
- Debit cash/card/bank clearing and credit receivables for the recorded tender allocations.
- Debit the sales-discount contra-revenue account for discounts.
- Credit sales revenue for subtotal less discounts.
- Credit output tax liability for the tax snapshot.

For each POS return:
- Debit sales returns for the returned amount excluding the returned tax.
- Debit output tax liability to reverse the original output tax.
- Credit the original refund tender's cash/card/bank account.

Journals are posted automatically in the same transaction as the POS source record when mappings are valid. A unique source link prevents duplicate journals on replay. Missing mappings, invalid mapped accounts, missing tax mapping for taxable activity, unbalanced source values or closed fiscal periods leave a durable pending integration with a diagnostic reason rather than silently creating a partial journal.

API:
- GET/PUT `/api/v1/accounting/pos-mapping`
- GET `/api/v1/accounting/pos-integrations`
- POST `/api/v1/accounting/pos-integrations/post-pending`
- POST `/api/v1/accounting/pos-integrations/backfill`

This integration does not execute external refunds or settle payment-provider clearing accounts; those remain separate payment-provider and reconciliation workflows. Account types, base-currency consistency and tax treatment require finance configuration and review.

The Accounting workspace now includes a POS ledger-mapping form, integration status table, pending-post action and legacy-source backfill action. Mapping controls are manager-authorized; integration status is available to users with accounting read access.
