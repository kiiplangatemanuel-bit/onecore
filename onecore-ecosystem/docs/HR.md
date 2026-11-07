# HR, attendance and payroll

This module provides employee master records, leave requests, attendance/timekeeping,
effective-dated payroll profiles, controlled payroll runs, Kenya statutory calculations,
payslips, accounting journal posting and salary payment preparation. See the Kenya
payroll sections below for the statutory calculation and integration boundaries.

## Employee directory
- `POST /api/v1/hr/employees` — manager-only employee creation.
- `GET /api/v1/hr/employees` — tenant/branch-scoped employee list.
- Employee numbers are unique per organization. An employee can optionally be linked
  to an active user membership in the same organization.

## Leave requests
- `POST /api/v1/hr/leave-requests` — employee self-service when the employee profile
  is linked to the signed-in user; HR managers may submit on behalf of staff.
- `GET /api/v1/hr/my-leave-requests` — employee's own leave history.
- `GET /api/v1/hr/leave-requests` — manager-only leave queue.
- `POST /api/v1/hr/leave-requests/{id}/decision` — manager approval/rejection.

Leave types: annual, sick, compassionate, unpaid, parental and other. Working days
are counted inclusively excluding Saturdays and Sundays. Overlapping pending or
approved requests for the same employee are rejected. Decisions require manager
permission; an employee cannot approve their own request.

## Remaining HR limitations
- Leave entitlement, accrual, carry-forward, balance ledger and automatic leave deduction are not implemented.
- Public holidays are not excluded; no organization holiday calendar is implemented.
- Employee document store, contract management, performance, recruitment, training, expense claims and disciplinary workflows remain outstanding.
- Attendance is currently a basic clock-in/out record. Overtime and shift pay are calculated only from HR-approved inputs; attendance-driven overtime approval and shift roster integration remain outstanding.
- Payroll provider, statutory filing, bank account vaulting, full reversal accounting and independent production assurance limitations are listed in the payroll completion section below.


## Attendance and timekeeping

- `POST /api/v1/hr/attendance/clock-in` starts a server-timestamped attendance session
  for the active employee profile linked to the signed-in user.
- `POST /api/v1/hr/attendance/clock-out` closes the current UTC-day session and
  calculates completed whole minutes from server timestamps.
- `GET /api/v1/hr/my-attendance` lists the signed-in employee's recent sessions.
- `GET /api/v1/hr/attendance` provides a branch-scoped team report to HR managers.
- Unique organization/employee/date constraint prevents duplicate sessions; repeated
  clock-in/out requests return HTTP 409 instead of silently changing time records.
- Clock actions require the employee's own active linked profile and create audit
  events. Team reporting requires manage permission.

This increment records one session per UTC calendar day. It does not yet support
organization time zones, shifts, breaks, overtime, geofencing, biometric devices,
offline attendance, manager corrections, multiple sessions per day, approval,
payroll integration or statutory time calculations. Worked minutes are elapsed
clock minutes, not paid hours. Deployments in other time zones should not use the
UTC date as a local payroll day until organization timezone handling is added.



## Payroll profiles, controlled runs and payslip snapshots

This increment adds a controlled payroll preparation and approval workflow. It
calculates amounts entered from an effective-dated employee pay profile and
itemized earnings/deductions. It is a payroll register, not a jurisdiction-certified
tax engine or payment service.

### Payroll profiles

- `POST /api/v1/hr/payroll/profiles` creates an effective-dated base pay profile
  for an active employee. The base amount is the employee's pay for one complete
  payroll period, not an annual salary.
- `GET /api/v1/hr/payroll/profiles` lists profiles visible to HR managers.
- Profile date ranges cannot overlap for the same employee. A new rate is added
  with a new effective date rather than overwriting a prior rate.

### Payroll runs and adjustments

- `POST /api/v1/hr/payroll/runs` creates a draft run for all active, eligible
  employees visible to the manager. Every included employee must have exactly one
  profile covering the complete run period; all profiles must use the same currency.
- `GET /api/v1/hr/payroll/runs` and
  `GET /api/v1/hr/payroll/runs/{run_id}` list runs and detailed line snapshots.
- `POST /api/v1/hr/payroll/runs/{run_id}/items` adds a one-time earning or
  deduction to an employee line while the run remains draft. Client item IDs are
  tenant-unique and canonical request hashes make identical retries idempotent.
- Gross pay equals base period pay plus earnings. Net pay equals gross pay minus
  deductions. A deduction total greater than gross pay is rejected.
- `POST /api/v1/hr/payroll/runs/{run_id}/approve` freezes a draft run. The creator
  cannot approve their own run; another manager with access to every included
  branch must approve it. Approved runs and their lines/items are immutable through
  these APIs.
- `GET /api/v1/hr/payroll/my-payslips` exposes approved payslip snapshots only to
  the employee account linked to that employee record.

### Controls and explicit boundaries

Payroll records and amounts are tenant-scoped, branch-checked, audited and retained
as snapshots. Runs cannot overlap another payroll period in the same organization.
A run cannot mix currencies. Profiles must cover the whole period. No employee
bank account or national identifier is collected by this increment.

The system does **not** calculate PAYE, NSSF, SHIF, housing levy, pension, benefits
tax, overtime premiums, statutory reliefs, leave pay, garnishments or employer
contributions. Earning and deduction items are explicitly supplied by authorized
payroll staff; they are not represented as statutory calculations. No payment
instruction, bank file, M-Pesa payout, payslip PDF/email, payroll journal or
accounting posting is generated. Validate applicable Kenyan and other local
employment/tax rules with qualified professionals before using the figures for
payment or statutory filing.


## Kenya payroll completion

### Statutory rule packs

- `POST /api/v1/hr/payroll/statutory-rules/seed-kenya-2026` installs the effective-dated Kenya 2026 pack once per organization.
- `GET /api/v1/hr/payroll/statutory-rules` lists all versions and their evidence sources.
- `POST /api/v1/hr/payroll/statutory-rules` creates a new draft version. `POST /api/v1/hr/payroll/statutory-rules/{id}/activate` activates it only when its date range does not overlap another active version.
- A payroll run selects exactly one active rule version using its period end date. The entire rule pack is copied into each immutable payroll calculation snapshot.
- Current Kenya 2026 defaults: PAYE monthly bands 10%, 25%, 30%, 32.5%, 35%; resident personal relief KES 2,400/month; NSSF Year 4 effective 1 February 2026 at 6% employee and employer, LEL KES 9,000 and UEL KES 108,000; SHIF 2.75% of gross salary with KES 300 minimum and no employer match; Affordable Housing Levy 1.5% employee and 1.5% employer.
- PAYE chargeable pay applies the configured eligible deductions, including SHIF, employee AHL, qualifying NSSF/registered pension contributions within the aggregate KES 30,000 monthly limit, mortgage interest within KES 30,000, and PRMF within KES 15,000. Insurance relief is 15% subject to KES 5,000/month. Resident personal relief is not applied to non-residents. Meal and disability exemptions require employee declarations/supporting evidence; the disability certificate details must be retained by HR.
- Statutory rules are not silently overwritten. New rates must be introduced as a new effective-dated version with source evidence and activation audit.

### Payroll calculation, approval and accounting

- `POST /api/v1/hr/payroll/runs/{id}/calculate-kenya` calculates from approved payroll lines/items and supplied per-employee pay inputs. It accepts complete calendar-month payroll periods because the configured PAYE bands, NSSF ceilings and SHIF minimum are monthly.
- Per-employee inputs support employment proration, overtime hours/rate/multiplier, shift allowance, cash allowances, taxable benefits, meal benefits, employee pension, mortgage interest, PRMF and insurance premium.
- Statutory contribution bases are separate from total cash gross: NSSF pensionable earnings, SHIF gross salary/wage and Housing Levy gross monthly salary default to prorated base pay plus the explicitly supplied `regular_cash_allowances`. One-off earnings, overtime and bonuses are excluded from these default bases; employers can supply the three explicit contribution-base overrides when the employee's approved fixed-pay structure requires it. `regular_cash_allowances` is a separate pay component included in cash gross, not merely a tax-only amount.
- Every employee calculation stores an immutable SHA-256 snapshot with the full statutory rule version and component breakdown. Recalculation of the same run is rejected; create a new run for corrected payroll.
- `GET /api/v1/hr/payroll/runs/{id}/snapshots` provides the review view.
- `POST /api/v1/hr/payroll/runs/{id}/approve-calculation` enforces maker-checker separation and validates snapshot integrity/count.
- `POST /api/v1/hr/payroll/runs/{id}/post-journal` posts a balanced journal using explicit tenant-owned chart-of-account IDs. Map salary expense, PAYE, NSSF, SHIF, Housing Levy, pension and other deduction liabilities. A duplicate payroll journal is rejected.
- `GET /api/v1/hr/payroll/my-history` returns only the signed-in employee's approved/paid payroll snapshots.

### Payment processing and reconciliation

- `POST /api/v1/hr/payroll/runs/{id}/payment-batches` prepares a bank or M-Pesa batch after payroll approval.
- Bank CSV export is available from `GET /api/v1/hr/payroll/payment-batches/{id}/bank-file`; bank account identifiers are intentionally not invented or exported. A secure employee bank-detail capture/approval workflow and institution-specific file format must be configured before bank upload.
- M-Pesa salary submission uses Safaricom Daraja B2C when `INTEGRATION_MPESA_ENABLED=true`, `MPESA_BASE_URL`, `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, `MPESA_SHORTCODE`, `MPESA_INITIATOR_NAME`, `MPESA_SECURITY_CREDENTIAL`, `MPESA_B2C_RESULT_URL` and `MPESA_B2C_TIMEOUT_URL` are configured. Optional `MPESA_B2C_COMMAND_ID` defaults to `SalaryPayment`. The callback gateway must sign normalized payloads using `PAYROLL_PROVIDER_CALLBACK_SECRET`. It sends one employee instruction at a time and does not mark payment paid from an accepted/queued response. B2C amount must be whole KES; decimal salaries are rejected rather than silently rounded.
- Provider callbacks must arrive through a trusted webhook gateway that validates Daraja's callback and forwards a normalized payload signed with `PAYROLL_PROVIDER_CALLBACK_SECRET`. The application verifies HMAC signatures, requires a provider transaction reference and prevents a settled payment from being downgraded.
- Failed payments can be retried; verified payment reversals require an external reversal reference and reason. Bank reconciliation matches statement references and exact amounts, and reports unmatched rows.
- Payment and reversal records are audited. No M-Pesa or bank credential is stored in payroll records.

### Reports

- `GET /api/v1/hr/payroll/reports/statutory?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD` produces employee-level snapshots and statutory totals.
- `GET /api/v1/hr/payroll/reports/analytics` summarizes payroll runs and totals.
- `GET /api/v1/hr/payroll/year-end/{year}` produces a year-end reconciliation workpaper.
- `GET /api/v1/hr/payroll/my-history` is the employee self-service history endpoint; existing `/hr/payroll/my-payslips` remains available for approved payslip summaries.

### Production boundaries and controls

- Statutory rate values are sourced from KRA PAYE guidance, KRA PAYE amendment guidance, KRA Housing Levy notice, NSSF Year 4 (2026) notice and the Social Health Insurance Regulations 2024. See source links in the seeded rule pack. The pack must be revalidated by Kenyan payroll/tax professionals before each payroll year and before live use.
- Payroll per-employee extras (residency, qualifying pension, mortgage, PRMF, insurance, meal benefit, disability certificate, proration, overtime and allowances) are supplied by authorized HR input and must be supported by employee documents and approval policy. The application does not infer attendance-based overtime automatically; it calculates supplied, approved hours/rates.
- Daraja callback delivery requires a secure gateway because Daraja's B2C result callback is not natively an HMAC-signed webhook. Bank API execution, employee bank account vaulting, KRA iTax filing, SHA employer portal filing, NSSF filing, and remittance payment are not performed by this increment.
- The accounting journal requires explicit account mapping and posts through the shared accounting ledger. A full statutory payment remittance clearing/reconciliation, payroll reversal journal, PostgreSQL load/concurrency tests, provider sandbox/UAT, pen test, data-protection review and customer signoff remain release gates.
- Payroll data is highly sensitive. Deploy with HTTPS, least-privilege HR permissions, encrypted backups, key management, retention policy and access monitoring. This increment is not legal, tax or statutory certification.
