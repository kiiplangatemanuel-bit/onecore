# Finance, SACCO, Microfinance and Chama

Master specification category: **10**

## Source scope
Members/KYC; savings, deposits, withdrawals, shares/contributions; groups; loan products/applications/assessment/approval/disbursement; interest, penalties, schedules and repayments; guarantors/collateral; statements, delinquency/restructuring, dividends, portfolio/risk reports, M-Pesa/banks, member portals, meetings, voting/resolutions and AI insights.

## Current implementation status
**Partial — member register and protected KYC review only.** This is not a complete SACCO, Microfinance or Chama application.

Implemented slice:
- Tenant- and branch-scoped member registration, listing and safe member summaries.
- Tenant-unique member numbers, keyed identity fingerprints and idempotent create requests.
- Fernet encryption for national ID, date of birth and postal address.
- Protected KYC detail access with reason capture and audit events.
- Four-eyes KYC review: the creator cannot decide their own submission; the reviewer must have recently accessed the protected details.
- PostgreSQL forced RLS, CI runtime-role behavior tests, API and workspace at /sacco.

See docs/SACCO_MEMBERSHIP_KYC.md for roles, key configuration, endpoints and operational caveats.

## Remaining implementation
Savings accounts, deposits/withdrawals, immutable share/contribution ledger, groups/chama, loan products and applications, affordability assessment, guarantors/collateral, multi-level approvals, disbursement, interest/penalty schedules, repayments, arrears/restructuring, dividends, statements, member portals, meetings/voting, portfolio risk analytics, M-Pesa/bank integrations, monitoring, backup/restore, end-to-end UAT and production role rehearsal remain outstanding.

The module must remain partial/disabled for production use until its complete category-specific acceptance evidence is reviewed.
