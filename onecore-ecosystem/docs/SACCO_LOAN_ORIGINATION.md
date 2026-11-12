# SACCO loan origination and credit governance

This increment adds a limited loan-origination workflow under master-specification category 10. It is a domain workflow, not a complete lending or microfinance platform.

## Included workflow

1. A tenant SACCO manager creates a loan product with organization currency, principal and term bounds, annual reducing-balance rate, maximum debt-service ratio, guarantor count and collateral requirement.
2. An authorized officer submits a loan application for an active, KYC-verified member. The request carries an organization-scoped idempotency key and records net monthly income, existing debt, purpose and a projected first repayment date.
3. A designated credit officer calculates the reducing-balance installment and debt-service ratio. Applications above the configured ratio remain ineligible for approval; the automated calculation is a screening control, not a complete credit score or an adverse-action engine.
4. Guarantors are added as active SACCO members. Their consent is recorded by a different staff member against a signed-form evidence reference. This is a staff-recorded, in-person attestation, not verified member self-service or a digital signature.
5. Collateral is recorded with a document reference and declared value. A different authorized verifier records the verification decision. If the product requires collateral, verified declared value must cover the principal.
6. A separate credit approver, who is neither the application creator nor the assessor, approves or rejects the application.
7. Approval creates a projected reducing-balance schedule with rounded currency amounts and calendar-month due dates.
8. An independent manager records evidence for the full approved principal, including channel, value date and external bank statement/provider/cash-voucher reference. Partial disbursement is rejected.
9. A separate SACCO treasurer reviews and verifies or rejects the evidence. Only a verified decision changes the application to active and activates the schedule. Rejected evidence can be replaced with a new idempotency key; only one pending and one verified disbursement are allowed per application.

## API

- POST /api/v1/sacco/loan-products — create a product (organization administrator or SACCO manager).
- GET /api/v1/sacco/loan-products — list active products available to the caller's branch scope.
- POST /api/v1/sacco/loan-applications — submit a member loan request.
- GET /api/v1/sacco/loan-applications and GET /api/v1/sacco/loan-applications/{id} — tenant/branch-scoped application register.
- POST /api/v1/sacco/loan-applications/{id}/guarantors and POST /api/v1/sacco/loan-guarantors/{id}/consent — record guarantor and independent consent evidence.
- POST /api/v1/sacco/loan-applications/{id}/collateral and POST /api/v1/sacco/loan-collateral/{id}/verification — record collateral and independent verification.
- POST /api/v1/sacco/loan-applications/{id}/assessment — calculate affordability and record credit assessment.
- POST /api/v1/sacco/loan-applications/{id}/decision — independent approval/rejection and projected schedule generation.
- GET /api/v1/sacco/loan-applications/{id}/schedule and /summary — scoped schedule and application evidence.
- POST /api/v1/sacco/loan-applications/{id}/disbursements — record full-principal settlement evidence for independent review.
- GET /api/v1/sacco/loan-applications/{id}/disbursements — list tenant/branch-scoped disbursement evidence history.
- POST /api/v1/sacco/loan-disbursements/{id}/verification — independent treasurer verification or rejection.

## Financial and security boundaries

- Loan products, applications, guarantors, collateral and installments are tenant-owned and ENABLE/FORCE RLS in PostgreSQL.
- Composite foreign keys keep loan applications, guarantors, collateral and installments attached to same-tenant members, products and applications.
- API grants are least-privilege: product and installment tables are insert/read only; workflow tables expose only the assessment, decision, consent and verification columns that the API changes.
- Branch access is checked before members, products and applications are read or changed. Custom SACCO roles separate product management, application entry, credit assessment, approval, guarantor consent and collateral verification.
- Creation, assessment, consent, collateral verification, credit decisions and disbursement request/review create audit events.
- Disbursement requests are organization-idempotent, tenant-consistent by composite foreign key, branch-scoped through the parent application and protected by forced PostgreSQL RLS. Partial unique indexes allow only one pending and one verified disbursement per application.
- The API role has SELECT/INSERT and only the review-column UPDATE grants on disbursement evidence; installment UPDATE is limited to the schedule status field. PostgreSQL blocks mutation/deletion of reviewed disbursement evidence.
- The disbursement requester must be distinct from the application creator, assessor and credit approver. The reviewer must also be distinct from the requester and all three application actors.
- A guarantor cannot be the borrower. A creator cannot record guarantor consent or collateral verification for their own submission. An application creator cannot assess or decide the same loan; an assessor cannot decide it.
- A guarantor's combined pending and accepted guarantee amount cannot exceed the principal; accepted guarantees must cover the principal when the product requires guarantors.
- The affordability calculation uses a fixed reducing-balance installment. It does not include fees, insurance, penalties, variable rates, grace periods or member-wide bureau data.

## Explicit limitations

- The new disbursement workflow records staff-reviewed evidence only. It does not initiate a bank/M-Pesa/cash payment or independently query a provider. A verified status means an authorized treasurer attested to the external reference; it is not provider certification or a signed settlement callback.
- Only the full approved principal can be recorded; split/partial disbursement is not supported. The first contractual repayment date must follow the stated disbursement value date.
- The schedule changes from projected to active only after staff verification. No installment repayment allocation, partial/early settlement, interest accrual, penalty accrual, arrears ageing, collections, rescheduling, restructuring, write-offs, loan reversals or member statements are included.
- Consent references and collateral document references are identifiers only. This increment does not upload or verify the underlying documents or provide member-facing digital consent.
- No savings/share offset, guarantor exposure aggregation, collateral valuation service, credit-bureau connection, portfolio/risk analytics or accounting general-ledger posting is included.
- Product update/deactivation, product-specific fees, interest-method configuration and approval matrices beyond the four-eyes separation remain open.
- Production Supabase role provisioning, provider credentials/UAT, backup/restore, monitoring, load tests, security review and member UAT remain release gates.

## Verification

Migration 0068_sacco_loan_origination creates the five origination tables; migration 0069_sacco_loan_disbursement adds disbursement evidence, active-loan status and forced tenant RLS. CI provisions a disposable PostgreSQL NOBYPASSRLS role and exercises cross-tenant visibility and writes. The API/UI tests cover product validation, idempotency, branch/tenant scope, independent assessment/consent/collateral/approval, disbursement segregation, rejection/retry and schedule activation. These tests do not establish production database-role readiness or provider settlement.
