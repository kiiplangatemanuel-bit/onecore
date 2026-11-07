# HR employee directory and leave workflow

This is the first HR vertical slice. It provides employee master records and a basic
leave request/approval workflow. It is not a payroll or statutory-compliance system.

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

## Explicit limitations
- No leave entitlement, accrual, carry-forward, balance ledger or automatic deduction.
- Public holidays are not excluded; no organization holiday calendar is implemented.
- No employee document store, contract management, attendance/time tracking, shifts,
  performance, recruitment, training, expense claims or disciplinary workflow.
- No payroll run, payslip, statutory tax, pension, social-security or health-insurance
  calculations, payment file or payroll accounting integration.
- No manager delegation, multi-step approvals, notifications, mobile employee portal,
  PostgreSQL concurrency testing, security review or customer UAT.

Do not use this module to calculate or pay statutory payroll obligations until
jurisdiction-specific rules and professional validation are implemented.


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
