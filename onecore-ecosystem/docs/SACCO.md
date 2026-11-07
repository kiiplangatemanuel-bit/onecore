# OneCore SACCO member, savings and loan origination

This increment adds the initial tenant-scoped SACCO workflow. It is an operational
recordkeeping foundation, not a regulated core-banking or credit-management system.

## Member and KYC workflow

- `POST /api/v1/sacco/members` registers a member with a tenant-unique member number.
- `GET /api/v1/sacco/members` lists members visible within the caller's branch scope.
- New members start with `status=pending` and `kyc_status=pending`.
- `POST /api/v1/sacco/members/{member_id}/kyc-decision` is manager-only and records
  a verified/rejected decision, reviewer, timestamp and mandatory review note.
- Verified members become active. Rejected members cannot open accounts or apply
  for loans.
- Branch IDs are checked against the tenant and caller's branch scope.

## Savings, shares and contributions

- `POST /api/v1/sacco/accounts` opens a savings, shares or contributions account
  for a verified member.
- `GET /api/v1/sacco/accounts` lists accounts and derives balances from the
  append-only transaction ledger.
- `POST /api/v1/sacco/accounts/{account_id}/transactions` records deposits,
  savings withdrawals, share contributions or member contributions.
- Savings withdrawals require manager permission and cannot exceed the current
  available ledger balance. Shares and contributions are not withdrawable through
  this endpoint.
- Transaction idempotency keys are unique per tenant; an identical retry returns
  the original transaction, while reuse with different data returns HTTP 409.
- `GET /api/v1/sacco/accounts/{account_id}/transactions` returns chronological
  ledger entries and running balances.

## Loan product and application workflow

- `POST /api/v1/sacco/loan-products` creates a tenant-owned product with principal,
  annual rate, term and flat/reducing interest-method parameters.
- `GET /api/v1/sacco/loan-products` lists active products.
- `POST /api/v1/sacco/loan-applications` submits a KYC-verified member application
  inside product principal and term limits.
- `GET /api/v1/sacco/loan-applications` lists applications, optionally filtered
  by submitted/approved/rejected status.
- `POST /api/v1/sacco/loan-applications/{application_id}/decision` records a
  manager approval/rejection with reviewer, timestamp and note; applicant
  self-approval is blocked.
- Products marked as requiring guarantors cannot accept applications yet because
  guarantor capture and consent are not implemented.

## Workspace

The `/sacco` page provides member registration, KYC review, account opening,
savings ledger posting, loan product creation and application review. It requires
a valid OneCore login and organization ID. The UI records internal transactions
only; it does not send or receive money through an external payment provider.

## Important boundaries and remaining work

- Loan approval is not loan disbursement. There is no loan account, amortization
  schedule, interest accrual, repayment allocation, arrears, penalties, restructuring,
  guarantor records, collateral, credit scoring or write-off workflow.
- No M-Pesa, bank, card, mobile-wallet, standing-order or payment callback integration.
- No statutory/regulatory reporting, prudential returns, member dividends, share
  capital valuation, member statements or audited financial close.
- No automated double-entry journals linking member ledger transactions to the
  general ledger; no suspense/clearing accounts or bank reconciliation.
- No maker-checker separation for deposits; withdrawals and loan decisions use
  the coarse tenant `manage` permission rather than granular SACCO roles.
- No field-level encryption, document upload/verification, member consent portal,
  retention controls, AML/sanctions screening or compliance certification.
- No concurrency/load testing against PostgreSQL, branch-level reconciliation,
  offline/mobile member portal, notifications or production UAT.

Do not use this workflow as a live regulated financial service until the remaining
controls, accounting integration, payment-provider verification, security review
and jurisdiction-specific compliance are implemented and approved.


## Loan disbursement and servicing increment

- `POST /api/v1/sacco/loan-applications/{application_id}/disburse` records an
  approved application as a loan and creates its installment schedule.
- Flat schedules calculate simple interest over the approved term. Reducing-balance
  schedules calculate monthly interest on the remaining principal. Currency values
  are rounded to cents and the final installment reconciles the remaining principal
  and interest.
- `GET /api/v1/sacco/loans` lists loans; `GET
  /api/v1/sacco/loans/{loan_id}/schedule` returns installment due dates, due/paid
  amounts and status.
- `POST /api/v1/sacco/loans/{loan_id}/repayments` records partial or full repayments.
  Amounts are allocated to earliest unpaid installments, interest before principal.
  Overpayments are rejected; idempotency keys prevent duplicate repayment entries.
- `GET /api/v1/sacco/loans/{loan_id}/repayments` returns repayment allocations.
- A loan closes when scheduled principal and interest are both fully repaid.

**Disbursement boundary:** the endpoint records the disbursement instruction and
creates a loan balance/schedule. It does not transfer funds to a member, savings
account, bank or mobile-money wallet. Repayment endpoints record internal receipts;
they do not verify external settlement. Interest is fixed at origination and no
penalties, arrears accrual, rescheduling, early-settlement rebates or variable-rate
recalculation are provided. No general-ledger journal is automatically posted.


## Loan arrears ageing report

- Added read-only `GET /api/v1/sacco/loans/arrears?as_of=YYYY-MM-DD`.
- Reports overdue unpaid scheduled principal and interest as of the requested date,
  grouped into 1–30, 31–60, 61–90 and over-90-day ageing buckets.
- Provides per-loan overdue principal, overdue interest, total overdue, overdue
  installment count and oldest due date/days past due.
- Results are tenant-scoped and branch-filtered using the caller's accessible
  branches. The report is derived from scheduled installment due/paid values and
  does not mutate loan or schedule records.
- Added a SACCO workspace report form and contract tests.

Boundaries: this is scheduled-installment arrears visibility, not a full collections
or prudential classification engine. It does not accrue late fees, calculate
penalties, restructure loans, apply non-performing-loan rules, issue notices,
allocate recovery costs or create accounting journals. It does not reconcile
receipts with bank/mobile-money settlement. Validate policies and regulatory
ageing definitions with the SACCO before operational use.


## Loan guarantor and collateral controls

- Added persisted guarantor records linked to an active loan and a verified,
  active SACCO member. A borrower cannot guarantee their own loan, and guarantor
  registration requires a recorded consent reference.
- Guarantor records move from pending to approved/rejected, and approved records
  may later be released. The person who registers a guarantor cannot review it.
- Added persisted collateral records with type, description, owner, identifier and
  estimated value. Review may accept/reject pending collateral; acceptance requires
  assessed value, valuation reference and valuation date. Accepted collateral may
  later be released.
- Read/write endpoints are organization-scoped and enforce the loan's branch access.
  State changes record reviewer, timestamp, reason and an audit event.
- Migration: `0022_sacco_guarantor_collateral`.

Endpoints:
- `POST/GET /api/v1/sacco/loans/{loan_id}/guarantors`
- `POST /api/v1/sacco/loans/{loan_id}/guarantors/{guarantor_id}/review`
- `POST/GET /api/v1/sacco/loans/{loan_id}/collateral`
- `POST /api/v1/sacco/loans/{loan_id}/collateral/{collateral_id}/review`

Boundaries: consent references are recorded evidence identifiers, not a digital
signature or independently verified consent service. Collateral valuation data is
captured but not independently verified, registered, insured, perfected or legally
enforced. This increment does not calculate guarantee capacity, enforce aggregate
guarantee limits, perform credit bureau checks, generate legal forms or post
accounting entries. The SACCO must validate its policies and legal requirements.
