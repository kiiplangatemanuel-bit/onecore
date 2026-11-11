# SACCO savings and share subledger

This increment implements a limited member financial subledger for master-specification category 10. It is not a full SACCO, microfinance or chama accounting system.

## Posting rules

- Only members with status active (KYC verified) can receive financial transactions.
- Savings deposits and share contributions are recorded immediately as posted internal entries by org_admin, sacco_manager or sacco_treasurer.
- Savings withdrawal requests are created as pending_approval; they do not reduce the available balance until approved.
- A different org_admin or sacco_manager must approve or reject a withdrawal. The requester cannot decide their own request.
- Approval locks the member row and recomputes the savings balance before posting a negative ledger entry. An insufficient balance leaves the request pending and does not create a ledger entry.
- Share contributions are stored separately from savings. Share withdrawals/redemptions are deliberately not supported in this increment.
- Amounts use the tenant organization's configured currency and two decimal places. Multi-currency member accounts are not supported.
- Pending withdrawal requests are not reserved against the available balance. Each approval rechecks the current balance under a member-row lock; competing approvals cannot spend the same balance concurrently on PostgreSQL.
- A posted ledger entry is immutable. Corrections must be designed as compensating entries in a later reviewed increment; direct mutation/deletion is blocked by a PostgreSQL trigger and the API runtime role has no UPDATE/DELETE grant on the ledger table.

These endpoints record an internal accounting subledger event. They do NOT prove that cash was received, a bank transfer settled, or an M-Pesa payment succeeded. Do not treat a browser redirect or a typed reference as payment verification. Provider callbacks, settlement reconciliation, cash controls and general-ledger journal integration remain separate work.

## Roles

- sacco_treasurer: member registration, savings deposits, withdrawal requests and share contributions; no approval permission.
- sacco_manager: may record transactions and independently approve/reject withdrawals.
- org_admin: tenant-level financial transaction and withdrawal approval access.
- sacco_auditor: read-only balances and transaction history.
- sacco_officer and sacco_kyc_approver: no financial posting or withdrawal approval permission.

SACCO roles remain module-scoped; they do not inherit generic permissions for other OneCore modules. Tenant membership and branch scope are checked before member balances, transactions or decisions are accessed.

## API

- POST /api/v1/sacco/members/{member_id}/transactions — record a savings deposit, request a savings withdrawal or record a share contribution. Requires an idempotency key.
- GET /api/v1/sacco/members/{member_id}/transactions — tenant/branch-scoped transaction history, with optional account/status filters.
- GET /api/v1/sacco/members/{member_id}/balances — derived savings and share balances in the organization's base currency.
- POST /api/v1/sacco/transactions/{transaction_id}/decision — approve or reject a pending savings withdrawal with a mandatory note.

Idempotency keys are unique per organization. Replaying the same key and payload returns the original transaction; reusing it for a different request returns HTTP 409. Ledger balances are derived from signed entries, not from mutable cached balance columns.

## Database security

Migration 0067_sacco_member_ledger follows 0066_sacco_membership_kyc and creates:
- sacco_financial_transactions: workflow envelope for posted deposits/share contributions and pending/decided withdrawals.
- sacco_ledger_entries: immutable signed member subledger rows.

Both tables use PostgreSQL ENABLE/FORCE RLS with the tenant membership context and platform-admin boundary. The API receives SELECT/INSERT and only the decision columns it must update on the workflow table. It receives SELECT/INSERT only on ledger entries. A PostgreSQL trigger rejects all ledger UPDATE and DELETE statements, including attempts by a table owner subject to the trigger. CI uses a disposable NOBYPASSRLS role to verify cross-tenant visibility/writes and immutability.

If onecore_api is provisioned after the migration, apply the equivalent reviewed grants:

    GRANT SELECT, INSERT ON TABLE public.sacco_financial_transactions TO onecore_api;
    REVOKE UPDATE, DELETE ON TABLE public.sacco_financial_transactions FROM onecore_api;
    GRANT UPDATE (status, decided_by, decided_at, decision_note, updated_at)
      ON TABLE public.sacco_financial_transactions TO onecore_api;
    GRANT SELECT, INSERT ON TABLE public.sacco_ledger_entries TO onecore_api;
    REVOKE UPDATE, DELETE ON TABLE public.sacco_ledger_entries FROM onecore_api;
    GRANT USAGE, SELECT ON SEQUENCE public.sacco_financial_transactions_id_seq TO onecore_api;
    GRANT USAGE, SELECT ON SEQUENCE public.sacco_ledger_entries_id_seq TO onecore_api;

The migration only applies grants when onecore_api exists. Production Supabase role creation, grant rehearsal and live database verification remain deployment tasks.

## Remaining scope

- Savings product definitions, account opening terms, minimum balances, limits, notice periods, fees and interest.
- Share redemption, member exit, dividend declarations and allocation.
- Compensating reversals, corrections, maker-checker cashbook controls and full GL posting.
- Group/chama membership, group contributions, meetings, attendance, voting and resolutions.
- Loan products, applications, affordability/credit assessment, guarantors, collateral, approval matrices, disbursement, interest/penalty accrual, schedules, repayments, arrears and restructuring.
- Member statements, portals, notifications and portfolio/risk reports.
- M-Pesa/bank adapters, verified callbacks, settlement reconciliation, provider UAT and production approval.
- Production role rehearsal, queue/ledger monitoring, backup/restore, security review, load testing and member UAT.
