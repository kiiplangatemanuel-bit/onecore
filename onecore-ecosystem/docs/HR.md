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
