# HR and Payroll module

The module is no longer scaffold-only. The first database-backed employee, leave, statutory payroll, approval, payslip and accounting bridge implementation is documented in [HR_PAYROLL.md](../../../docs/HR_PAYROLL.md).

Daily attendance submission, overtime-minute calculation and independent HR approval are included from migration 0040. Approved overtime and unpaid leave feed payroll calculations and are captured in immutable payroll snapshots. One-off earnings and deductions are independently approved, applied once to payroll periods, captured in immutable payslip snapshots and accounted through a separately mapped liability account (migrations 0043–0044).

Production activation still requires controlled Alembic migrations, verified statutory source publications and effective dates, payroll parallel runs, finance/HR UAT and sign-off. Do not treat source URL validation as statutory certification.

The current payroll domain is canonical. Do not merge the legacy HR integration branch wholesale: it includes unrelated modules and duplicate payroll tables. See [the integration reconciliation](../../../docs/HR_PAYROLL.md#integration-reconciliation-legacy-hr-pr-69) for the scope mapping and explicitly unported payment-batch work.
