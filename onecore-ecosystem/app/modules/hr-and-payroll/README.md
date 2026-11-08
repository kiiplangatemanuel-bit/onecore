# HR and Payroll module

The module is no longer scaffold-only. The first database-backed employee, leave, statutory payroll, approval, payslip and accounting bridge implementation is documented in [HR_PAYROLL.md](../../docs/HR_PAYROLL.md).

Daily attendance submission, overtime-minute calculation and independent HR approval are included from migration 0040. The current attendance slice records and reviews time; it does not yet feed overtime or unpaid-leave adjustments into payroll calculations.

Production activation still requires controlled Alembic migrations, verified statutory source publications and effective dates, payroll parallel runs, finance/HR UAT and sign-off. Do not treat source URL validation as statutory certification.
