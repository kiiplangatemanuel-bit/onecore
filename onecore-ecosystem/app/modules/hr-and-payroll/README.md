# HR and Payroll

Master specification category: **11**

## Implementation status

The repository contains a database-backed first implementation of employee administration, leave approvals, configurable Kenyan statutory payroll rules, monthly payroll calculation, payslips and payroll-to-accounting journals. The module is **partially implemented**, not production-certified. The API is registered in `app/main.py`; the schema is managed by migrations `0037`–`0039`; and the authenticated React workspace is available at `/hr-portal`.

## Implemented workflows

- Tenant- and branch-scoped employee register and employee creation, including employment status and termination date.
- Leave requests with overlap checks, branch scope and requester/approver separation.
- Versioned PAYE, NSSF, SHIF and employee/employer Housing Levy rules with effective dates, official KRA/NSSF/SHA source evidence and independent approval. No statutory rates are shipped as defaults.
- Monthly payroll calculation with recurring salary, allowances, benefits, configured pension, hire/termination proration and immutable calculation/payslip snapshots.
- Payroll preparation, submission, independent approval, external payment-reference confirmation and role separation.
- Payroll accounting mapping, balanced accrual journal, settlement journal and pre-payment accrual reversal.
- Audit events, idempotency and tenant/branch authorization on the implemented lifecycle operations.

## API and implementation reference

See [HR_PAYROLL.md](../../../docs/HR_PAYROLL.md) for endpoint paths, calculation boundaries, accounting behavior, tests and release requirements. Key routes include:

- `GET/POST /api/v1/hr/employees`
- `POST /api/v1/hr/employees/{employee_id}/employment-status`
- `POST /api/v1/hr/employees/{employee_id}/leave`
- `GET /api/v1/hr/leave-requests` and `POST /api/v1/hr/leave-requests/{request_id}/decision`
- `GET/POST /api/v1/payroll/rule-sets` plus submit/approve actions
- `GET/POST /api/v1/payroll/runs` plus submit/approve/mark-paid actions
- `GET /api/v1/payroll/runs/{run_id}/payslips`
- `GET/PUT /api/v1/payroll/accounting-mapping`
- Payroll accrual posting and pre-payment journal reversal endpoints

## Remaining work before full production scope

Recruitment/ATS, onboarding/contracts, department and position master data, attendance/biometrics, shifts, timesheets, overtime and shift differentials, approved leave impact on payroll, one-off earnings/deductions, employee self-service, appraisals, training, discipline, statutory return generation/filing, statutory remittance and direct bank/M-Pesa transfer integrations are not represented as completed by this implementation. Monitoring, retention, disaster-recovery evidence, payroll parallel runs, statutory rule verification and formal HR/finance UAT are also required before production release.

Statutory source URLs and metadata are validated by the API, but the API does not independently verify the contents or certify legal compliance. Authorized payroll reviewers must check the applicable official publications and effective dates before activating any rule set. Payment references confirm externally completed transfers; they do not initiate transfers.
