# HR and Payroll

Master specification category: **11**

## Source scope
Employee profiles, recruitment/ATS, onboarding/contracts, departments/positions, attendance/biometrics, shifts, leave/overtime/timesheets, payroll, allowances/deductions/payslips/payments, configurable PAYE/NSSF/SHIF/AHL statutory rules, tax reports, appraisals, training, discipline, self-service and analytics.

## Implementation status
Scaffold only. This folder reserves the domain boundary; it is not a claim of production implementation.

## Required implementation
- Define domain entities, constraints, indexes and migrations.
- Add domain services and versioned API routes.
- Enforce tenant, branch and role authorization at the service layer.
- Add validation, approval workflows, audit events and idempotency where needed.
- Build responsive user/admin workflows and accessible states.
- Add unit, integration, security and end-to-end tests.
- Add monitoring, retention, backup/restore and operational documentation.
- Complete sandbox/UAT and release approval for external dependencies.


## Payroll preparation

The HR payroll slice supports effective-dated base pay per complete pay period,
draft run generation, explicit one-time earning/deduction items, manager approval
and approved payslip snapshots. It does not calculate statutory obligations or
execute payroll payments. See `docs/HR.md` for API contracts and boundaries.
