# Finance, SACCO, Microfinance and Chama

Master specification category: **10**

## Source scope
Members/KYC; savings, deposits, withdrawals, shares/contributions; groups; loan products/applications/assessment/approval/disbursement; interest, penalties, schedules and repayments; guarantors/collateral; statements, delinquency/restructuring, dividends, portfolio/risk reports, M-Pesa/banks, member portals, meetings, voting/resolutions and AI insights.

## Current implementation status
**Partial — member onboarding/KYC plus a first savings/share subledger.** This is not a complete SACCO, Microfinance or Chama application.

Implemented vertical slices:
- Tenant- and branch-scoped member registration, listing and safe member summaries.
- Tenant-unique member numbers, keyed identity fingerprints and idempotent create requests.
- Fernet encryption for national ID, date of birth and postal address.
- Protected KYC detail access with reason capture and audit events.
- Four-eyes KYC review: the creator cannot decide their own submission; the reviewer must have recently accessed the protected details.
- Member savings deposits and share contributions recorded in separate tenant-scoped subledgers.
- Savings withdrawals are pending until a different authorized manager approves; available balance is rechecked while the member row is locked.
- Balances are derived from immutable signed ledger entries. PostgreSQL RLS, append-only triggers and restricted API grants protect financial records.
- Member/KYC workspace and savings/share ledger controls at /sacco.

See:
- docs/SACCO_MEMBERSHIP_KYC.md for KYC roles, key configuration and operational caveats.
- docs/SACCO_SAVINGS_LEDGER.md for financial posting, approvals, balances and API contracts.

## Remaining implementation
Savings product configuration, withdrawal limits/notice periods, share redemption and member exit, accounting general-ledger journals, cash/bank reconciliation, correction/reversal workflows, groups/chama, loan products and applications, affordability assessment, guarantors/collateral, multi-level loan approvals, disbursement, interest/penalty schedules, repayments, arrears/restructuring, dividends, statements, member portals, meetings/voting, portfolio risk analytics, M-Pesa/bank adapters, monitoring, backup/restore, end-to-end UAT and production role rehearsal remain outstanding.

Do not mark or expose this partial slice as a production-ready SACCO, Microfinance or Chama product until the complete category-specific acceptance evidence is reviewed.
