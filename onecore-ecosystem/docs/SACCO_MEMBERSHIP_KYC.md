# SACCO membership and KYC

This is the first implemented vertical slice for master-specification category 10 (Finance, SACCO, Microfinance and Chama). It covers the tenant/branch-scoped member register and an auditable four-eyes KYC decision. It does not implement savings, shares, loans, groups, repayments or provider transfers.

## Data protection

- National ID, date of birth and postal address are encrypted together with Fernet before storage.
- A separate keyed HMAC-SHA256 fingerprint supports duplicate detection without storing the raw identity number or using an unkeyed hash.
- SACCO_KYC_ENCRYPTION_KEY and SACCO_KYC_HMAC_KEY are required before member creation. The API fails closed if either is missing or invalid.
- Normal member list/detail responses never include encrypted or decrypted identity data.
- Only org_admin, sacco_manager and sacco_kyc_approver can access protected KYC details. Each access requires a reason and creates an audit event.
- A KYC decision requires a recent protected-detail access by the same reviewer. The creator cannot approve or reject their own submission.
- KYC keys must be backed up in the deployment secret manager. Do not rotate either key without a controlled re-encryption/fingerprint migration plan; loss of the encryption key makes stored KYC details unrecoverable.

## Roles

- sacco_officer: register and read members.
- sacco_manager: register/read members and review KYC.
- sacco_kyc_approver: read members and review KYC.
- sacco_treasurer: read and register members.
- sacco_auditor: read-only member register.
- org_admin: tenant administrator access.

Branch-restricted memberships must supply a branch they are authorized to access. A supplied branch must be active and belong to the same organization.

## API

- POST /api/v1/sacco/members — register a member with an idempotency key.
- GET /api/v1/sacco/members — list members with optional status/branch filters and pagination.
- GET /api/v1/sacco/members/{member_id} — safe member summary.
- GET /api/v1/sacco/members/{member_id}/kyc-details?reason=... — protected KYC details; reason is required and access is audited.
- POST /api/v1/sacco/members/{member_id}/kyc-review — independent verify/reject decision after protected details have been opened.

A verified member transitions from pending_kyc to active. A rejected member transitions to rejected. The review is one-way in this increment; resubmission, suspension/reactivation and exit workflows remain future work.

## Operations

Generate independent keys and store them only in the deployment secret manager:

- SACCO_KYC_ENCRYPTION_KEY: Fernet key generated with Fernet.generate_key().
- SACCO_KYC_HMAC_KEY: at least 32 random bytes encoded as a secret string.

The migration adds forced PostgreSQL RLS on sacco_members. CI provisions a disposable NOBYPASSRLS role and tests cross-tenant reads/writes. Production Supabase roles and grants still require a separate rehearsal.

## Remaining scope

Savings accounts, deposits/withdrawals, share/contribution ledger, groups/chama, loan products/applications, affordability assessment, guarantors/collateral, multi-level approvals, disbursement, interest/penalty schedules, repayments, delinquency/restructuring, dividends, statements, member portals, meetings/voting, risk analytics, M-Pesa/bank adapters, monitoring alerts, full UAT and production operations are not part of this slice.
