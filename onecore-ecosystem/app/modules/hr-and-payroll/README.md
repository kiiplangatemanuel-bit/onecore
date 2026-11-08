# HR and Payroll

Master specification category: **11**

## Implementation status

The repository contains a database-backed HR and payroll implementation with employee lifecycle controls, leave approvals, configurable Kenyan statutory rules, monthly payroll calculation, payslips, payroll accounting journals, attendance review, approved overtime and unpaid-leave payroll adjustments, and one-off earning/deduction approvals. The module is **partially implemented**, not production-certified.

The API is registered in `app/main.py`; HR/payroll schema changes are managed by migrations `0037`–`0043`; and the authenticated React workspace is available at `/hr-portal`.

## Implemented workflows

- Tenant- and branch-scoped employee register, creation and termination controls.
- Leave requests with overlap checks, branch scope and requester/approver separation.
- Versioned PAYE, NSSF, SHIF and employee/employer Housing Levy rules with effective dates, official KRA/NSSF/SHA source evidence and independent approval. No statutory rates are shipped as defaults.
- Monthly payroll calculation with recurring salary, allowances, benefits, configured pension, hire/termination proration and immutable calculation/payslip snapshots.
- Daily attendance submissions, derived worked/overtime minutes, idempotency and independent approval.
- Approved overtime and approved unpaid leave included in payroll calculation snapshots.
- One-off employee earnings and deductions with reason, effective date, idempotency, independent approval/rejection, once-only payroll assignment and immutable payslip detail.
- Payroll preparation, submission, independent approval, external payment-reference confirmation and role separation.
- Payroll accounting mapping, balanced accrual journal, settlement journal, pre-payment reversal and separate other-deductions liability mapping.
- Audit events, tenant/branch authorization and concurrency controls on implemented lifecycle operations.

## API and implementation reference

See [HR_PAYROLL.md](../../../docs/HR_PAYROLL.md) for endpoint paths, calculation boundaries, accounting behavior, tests and release requirements. Key routes include:

- `GET/POST /api/v1/hr/employees`
- `POST /api/v1/hr/employees/{employee_id}/employment-status`
- `POST /api/v1/hr/employees/{employee_id}/leave`
- `GET /api/v1/hr/leave-requests` and `POST /api/v1/hr/leave-requests/{request_id}/decision`
- `GET/POST /api/v1/hr/attendance` and `POST /api/v1/hr/attendance/{attendance_id}/decision`
- `GET /api/v1/hr/payroll-adjustments`
- `POST /api/v1/hr/employees/{employee_id}/payroll-adjustments`
- `POST /api/v1/hr/payroll-adjustments/{adjustment_id}/decision`
- `GET/POST /api/v1/payroll/rule-sets` plus submit/approve actions
- `GET/POST /api/v1/payroll/runs` plus submit/approve/mark-paid actions
- `GET /api/v1/payroll/runs/{run_id}/payslips`
- `GET/PUT /api/v1/payroll/accounting-mapping`
- Payroll accrual posting and pre-payment journal reversal endpoints

## Remaining work before full production scope

Shift rosters, shift differentials, biometrics/device attendance, timesheet correction workflows, recruitment/ATS, onboarding/contracts, department and position master data, employee self-service, appraisals, training, discipline, statutory return generation/filing, statutory remittance and direct bank/M-Pesa transfer integrations are not represented as completed by this implementation.

Monitoring, retention, disaster-recovery evidence, payroll parallel runs, statutory rule verification, security testing and formal HR/finance UAT are also required before production release.

Statutory source URLs and metadata are validated by the API, but the API does not independently verify the contents or certify legal compliance. Authorized payroll reviewers must check the applicable official publications and effective dates before activating any rule set. Payment references confirm externally completed transfers; they do not initiate transfers.
