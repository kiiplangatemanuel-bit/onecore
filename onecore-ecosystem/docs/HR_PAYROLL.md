# HR and Payroll domain API

This implementation replaces the former HR/Payroll scaffold with the first database-backed domain slice.

## Implemented
- Tenant- and branch-scoped employee profiles with unique employee numbers, monthly base salary, recurring allowance/benefit components, pension contribution, scheduled daily minutes, optional employer-configured overtime multiplier and employment status.
- Leave requests with employee/branch ownership checks, decision audit events and requester-versus-approver separation.
- Daily attendance submissions with timezone-aware clock timestamps, break and scheduled-minute validation, derived worked/overtime minutes, tenant/branch scope, idempotent retries, one record per employee/day, and independent HR approval/rejection.
- Versioned statutory rule sets with effective dates, progressive PAYE bands, personal relief, pension deduction limit, NSSF contribution tiers, SHIF rate and employee/employer Housing Levy rates.
- Rule-set submission and independent approval. Activation is blocked when an active rule set overlaps the proposed effective date range.
- Official HTTPS source references are required for KRA, NSSF and SHA. The API validates the official host names and evidence metadata; it does not scrape or independently certify the contents. An authorized reviewer must check the source publications and dates before activation. No statutory rates are shipped as defaults.
- Monthly payroll runs use only an approved rule set covering the entire month and active employees in the selected tenant/branch/currency.
- Gross pay includes configured recurring allowances and benefits. Base salary, recurring components and employee pension are prorated by eligible calendar days for hires/terminations during the month.
- Approved attendance overtime minutes are included in payroll only when the employee has an explicit overtime multiplier configured. Hourly pay is derived from monthly base salary and the employee's scheduled daily minutes using a documented 26-day payroll divisor; the multiplier is employer policy, not a statutory rate.
- Approved unpaid leave is prorated into a gross-pay deduction for the days overlapping the payroll month. Pending/rejected leave and unapproved attendance do not affect payroll. The calculation snapshot records overtime minutes/earnings and unpaid-leave days/deductions.
- PAYE is progressive over the configured bands after the configured deductible pension amount and personal relief. NSSF is calculated by configured tiers. SHIF and Housing Levy use configured rates.
- Draft payroll calculation snapshots and individual payslip snapshots are persisted. Submitted runs require a different user to approve; the approver cannot also record payment. Payment references are confirmations only and do not initiate transfers.
- Idempotency key on payroll run creation; database uniqueness for employee numbers, rule versions, payroll idempotency keys and one payslip per employee per run.
- Payroll-to-accounting mapping validates expense, liability and bank account types against the tenant chart of accounts.
- Approved payroll posts a balanced accrual journal: gross earnings and employer contributions are debited; net pay and statutory/pension liabilities are credited.
- External payment confirmation creates a separate settlement journal debiting net payroll payable and crediting the configured bank account. It records the supplied payment reference and does not initiate a transfer.
- Payroll accrual journals can be reversed before payment with a reason; the original run is marked cancelled and the period may be recalculated under a new idempotency key. The reversal itself is an immutable posted journal.
- Tenant/branch permission checks and audit events for employee, leave, rule-set and payroll lifecycle actions.

## API paths
- `GET/POST /api/v1/hr/employees`
- `POST /api/v1/hr/employees/{employee_id}/employment-status`
- `POST /api/v1/hr/employees/{employee_id}/leave`
- `GET /api/v1/hr/leave-requests`
- `POST /api/v1/hr/leave-requests/{request_id}/decision`
- `GET /api/v1/hr/attendance`
- `POST /api/v1/hr/attendance`
- `POST /api/v1/hr/attendance/{attendance_id}/decision`
- `GET/POST /api/v1/payroll/rule-sets`
- `POST /api/v1/payroll/rule-sets/{rule_set_id}/submit`
- `POST /api/v1/payroll/rule-sets/{rule_set_id}/approve`
- `GET/POST /api/v1/payroll/runs`
- `POST /api/v1/payroll/runs/{run_id}/submit`
- `POST /api/v1/payroll/runs/{run_id}/approve`
- `POST /api/v1/payroll/runs/{run_id}/mark-paid`
- `GET /api/v1/payroll/runs/{run_id}/payslips`
- `GET/PUT /api/v1/payroll/accounting-mapping`
- `POST /api/v1/payroll/runs/{run_id}/post-to-accounting`
- `POST /api/v1/payroll/runs/{run_id}/reverse-accounting-journal`

## Calculation and release limitations
This slice is not yet a complete statutory payroll product or a production compliance certification. The current calculation model covers recurring monthly salary/allowances/benefits, configured pension, PAYE, NSSF, SHIF and Housing Levy. Attendance capture, review and overtime-minute calculation are implemented, and approved overtime and unpaid leave now feed the immutable payroll calculation snapshot. Shift differentials, one-off earnings/deductions, additional tax relief variants, employee self-service access, statutory return generation/filing, statutory remittance integrations, payment reversals and direct bank/M-Pesa transfer integrations remain follow-on work. The accrual journal, pre-payment accrual reversal and externally confirmed net-pay settlement journal are implemented; direct money movement is not.

Before production use, OneCore must run migrations 0037–0041 against a controlled database, validate rule sets against the applicable official publications and effective dates, execute payroll parallel runs/UAT, and obtain finance/HR sign-off.


## Integration reconciliation (legacy HR PR #69)

The former integration branch `feature/hr-payroll-runs` accumulated unrelated Healthcare, Pharmacy/Lab, SACCO, School and CRM changes and was based on an older application architecture. It must not be merged wholesale into `main`.

The current `main` HR domain is the canonical implementation. It uses `app/core/hr_payroll_models.py`, `app/api/hr_payroll.py`, migration chain `0037–0043`, and the Finance/HR payroll workspace. The legacy PR's separate `HRPayrollProfile`, `HRPayrollRun`, `HRPayrollLine` and generic-record payment implementation are not copied because they duplicate or conflict with the current tenant-scoped payroll model and its immutable calculation/payslip snapshots.

| Legacy PR #69 scope | Current canonical status |
| --- | --- |
| Employee directory and employment lifecycle | Implemented in the current HR API and workspace, including termination controls |
| Leave requests and independent decisions | Implemented in the current HR API |
| Attendance capture and approval | Implemented; approved overtime and unpaid leave feed payroll calculations |
| Kenya statutory PAYE, NSSF, SHIF and Housing Levy rules | Implemented as effective-dated, separately approved rule sets; official-source validation and HR/finance sign-off remain release gates |
| Payroll preparation, approvals and payslips | Implemented with immutable calculation snapshots and maker-checker controls |
| Payroll accounting accrual and reversal | Implemented with balanced journals and controlled pre-payment reversal |
| One-off earnings and deductions | Implemented on the current domain by the separate payroll-adjustments change set; retain its own review and CI gates |
| Legacy payment batches and bank reconciliation | Not transplanted: the old implementation depends on the duplicate payroll tables and generic Record storage. A provider-backed disbursement/reconciliation workflow must be designed against the current PayrollRun/PayrollPayslip model before implementation |
| Inherited Healthcare, Pharmacy/Lab, SACCO, School and CRM files | Excluded from HR integration; they must be delivered and reviewed through their own module branches |

This payment-batch implementation is a new, focused change against the canonical payroll domain. It does not copy the legacy generic-record payment tables or claim to initiate bank transfers. External payment references are supplied after funds have been sent through an independently operated bank/provider channel.


## Payroll payment batches and bank reconciliation (migration 0042)

- Create a payment batch from approved, positive-net payroll runs that have posted accrual journals and no settlement/reversal. Currency must be consistent. Each payroll run can be reserved by only one batch.
- Batch creation is idempotent by organization and caller-supplied key. The batch captures run IDs, branch, currency and net amount; item amounts are not recalculated from employee records.
- Batch submission and approval are separate actions. The approver must differ from both creator and submitter. Only the payroll payment role can record settlements, and the payment authorizer must differ from creator, submitter, approver and the accounting journal poster.
- Settlement supports partial batches. Each run receives its own external payment reference and balanced settlement journal. The API records confirmation only; it does not initiate a bank, M-Pesa or other provider transfer.
- Import bank statement lines as structured rows from a bank export. Exact reference, amount and currency matches are automatic; ambiguous or unmatched lines remain visible as exceptions. A finance reviewer can manually resolve an exception only when amount and currency exactly match a paid batch item, with a required audit note.
- A statement line and a payroll batch item can each be reconciled only once. Duplicate statement fingerprints are rejected. Cross-organization data is not visible or matchable.
- API paths: `GET/POST /api/v1/payroll/payment-batches`, `POST /api/v1/payroll/payment-batches/{id}/submit`, `POST /api/v1/payroll/payment-batches/{id}/approve`, `POST /api/v1/payroll/payment-batches/{id}/settlements`, `POST /api/v1/payroll/bank-statements/import`, `GET /api/v1/payroll/bank-statements`, and `POST /api/v1/payroll/bank-statements/{id}/resolve`.
