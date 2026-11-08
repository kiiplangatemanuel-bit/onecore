# HR and Payroll domain API

This implementation replaces the former HR/Payroll scaffold with the first database-backed domain slice.

## Implemented
- Tenant- and branch-scoped employee profiles with unique employee numbers, monthly base salary, recurring allowance/benefit components, pension contribution and employment status.
- Leave requests with employee/branch ownership checks, overlap detection, decision audit events and requester-versus-approver separation. Approved unpaid leave is prorated into the relevant payroll month.
- Branch-aware shift definitions, employee default shift assignment and daily attendance records with timezone-aware clock-in/out, scheduled/worked/overtime minutes and shift differential snapshots. Attendance records require a different HR user to approve before they can affect payroll.
- Versioned statutory rule sets with effective dates, progressive PAYE bands, personal relief, pension deduction limit, NSSF contribution tiers, SHIF rate and employee/employer Housing Levy rates.
- Rule-set submission and independent approval. Activation is blocked when an active rule set overlaps the proposed effective date range.
- Official HTTPS source references are required for KRA, NSSF and SHA. The API validates the official host names and evidence metadata; it does not scrape or independently certify the contents. An authorized reviewer must check the source publications and dates before activation. No statutory rates are shipped as defaults.
- Monthly payroll runs use only an approved rule set covering the entire month and active employees in the selected tenant/branch/currency.
- Gross pay includes configured recurring allowances and benefits. Base salary, recurring components and employee pension are prorated by eligible calendar days for hires/terminations during the month.
- Approved attendance overtime is calculated using the configured monthly standard hours and overtime multiplier; approved shift differential is calculated from the shift rate snapshot. Payroll is blocked while any selected employee has unresolved attendance in the target month.
- Approved unpaid leave reduces earned gross and statutory contribution bases; the unpaid-leave deduction is separately retained on the payslip snapshot.
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
- `GET/POST /api/v1/hr/shifts`
- `POST /api/v1/hr/employees/{employee_id}/default-shift`
- `GET/POST /api/v1/hr/attendance`
- `POST /api/v1/hr/attendance/{attendance_id}/decision`
- `POST /api/v1/hr/employees/{employee_id}/employment-status`
- `POST /api/v1/hr/employees/{employee_id}/leave`
- `GET /api/v1/hr/leave-requests`
- `POST /api/v1/hr/leave-requests/{request_id}/decision`
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
This slice is not yet a complete statutory payroll product or a production compliance certification. The current calculation model covers recurring monthly salary/allowances/benefits, configured pension, PAYE, NSSF, SHIF and Housing Levy. One-off earnings/deductions, additional tax relief variants, employee self-service access, statutory return generation/filing, statutory remittance integrations, post-payment reversals and direct bank/M-Pesa transfer integrations remain follow-on work. The accrual journal, pre-payment accrual reversal and externally confirmed net-pay settlement journal are implemented; direct money movement is not.

Before production use, OneCore must run migrations 0037–0039 against a controlled database, validate rule sets against the applicable official publications and effective dates, execute payroll parallel runs/UAT, and obtain finance/HR sign-off.
