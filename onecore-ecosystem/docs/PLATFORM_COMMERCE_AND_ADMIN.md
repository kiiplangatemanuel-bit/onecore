# Platform commerce, documents and administration

## Subscription billing

New durable tables:
- `subscription_plans`: administrator-managed plan catalogue and JSON entitlements.
- `organization_subscriptions`: tenant subscription lifecycle and immutable price/currency/interval snapshot.
- `subscription_payments`: idempotent payment references and platform verification decisions.

Customer API:
- `GET /api/v1/subscription-plans`
- `GET /api/v1/subscriptions/current`
- `POST /api/v1/subscriptions` (organization administrator; automatic renewal is rejected until a recurring mandate exists)
- `GET /api/v1/subscriptions/payments`
- `POST /api/v1/subscriptions/{id}/payments` (reference submission; idempotency key required)
- `POST /api/v1/subscriptions/{id}/cancel`

Platform API:
- `GET/POST/PATCH /api/v1/admin/platform/subscription-plans`
- `GET /api/v1/admin/platform/subscriptions`
- `GET /api/v1/admin/platform/subscription-payments`
- `POST /api/v1/admin/platform/subscription-payments/{id}/review`

A subscription becomes active only after a platform administrator verifies the external payment reference. Verified renewals extend the stored term using the price interval snapshot. This implementation does not initiate a recurring card charge or M-Pesa STK push, and plan entitlements are persisted but are not yet enforced as a centralized module-entitlement gate. Provider payment execution and entitlement enforcement remain explicit follow-on work; the UI does not claim an unconfigured payment gateway.

## Private files and document management

New tables:
- `managed_files`: tenant-scoped file/folder metadata, classification, integrity hash, scan state and soft-delete.
- `managed_file_shares`: hashed, expiring, download-limited public share tokens.
- `managed_file_versions`: immutable version history.

API:
- `GET /api/v1/files?parent_id=...`
- `POST /api/v1/files/folders`
- `POST /api/v1/files/upload` (multipart, maximum 20 MiB)
- `PATCH /api/v1/files/{id}` and `DELETE /api/v1/files/{id}`
- `GET /api/v1/files/{id}/download`
- `GET/POST /api/v1/files/{id}/versions`
- `GET /api/v1/files/{id}/versions/{version_id}/download`
- `POST /api/v1/files/{id}/shares`, `GET /api/v1/files/shares`, `POST /api/v1/files/shares/{id}/revoke`
- `GET /api/v1/files/shared/{token}/download`

Object content is held in a private S3-compatible bucket; database rows contain metadata and object keys only. Upload fails closed unless object storage and ClamAV scanning are configured. Download links are short-lived (five minutes). File classification limits listing, moving, sharing and download access. Public share tokens are stored only as hashes, expire, have a download cap and can be revoked.

Required backend environment:
- `INTEGRATION_OBJECT_STORAGE_ENABLED=true`
- `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, `S3_REGION`
- `SUPPORT_ATTACHMENT_SCANNING_ENABLED=true`
- `CLAMAV_HOST`, optional `CLAMAV_PORT` (default 3310), `CLAMAV_TIMEOUT_SECONDS`

Do not make the bucket public. Keep credentials server-side. Configure lifecycle/backup policies for the bucket and test restore before production use.

## Customer administration

- `GET /api/v1/members` lists the selected organization's members.
- `PATCH /api/v1/members/{membership_id}` updates role, branch scope and active state.
- Existing `/api/v1/invitations`, `/api/v1/branches`, and `/api/v1/domains` workflows are exposed in the customer workspace.

Only an organization administrator can change membership access. The API validates branch IDs against the active tenant and prevents removal or demotion of the last active organization administrator.

## Superadmin

All platform administration routes require `require_platform_admin`:
- `GET /api/v1/admin/platform/overview`
- `GET /api/v1/admin/platform/organizations` and `PATCH /organizations/{id}/status`
- `GET /api/v1/admin/platform/users` and `PATCH /users/{id}/status`
- `GET /api/v1/admin/platform/subscriptions`
- `GET/POST/PATCH /api/v1/admin/platform/subscription-plans`
- `GET /api/v1/admin/platform/subscription-payments`
- `GET /api/v1/admin/platform/audit`
- Existing protected notice creation, publishing, editing and withdrawal routes.

User suspension increments `auth_version`, invalidating existing access tokens. Root Superadmin accounts cannot be suspended through the ordinary user-status endpoint; a platform administrator cannot suspend another platform administrator. All state changes are audited. The UI route `/superadmin` is not linked from public navigation or indexed, but backend role checks—not route secrecy—are the security boundary.

This is a functional platform control surface, not the complete central CMS/operations specification. Content management for every public portal, maintenance windows, incident command, release management, security policy administration, tenant provisioning automation and high-risk dual-approval workflows still need their own domain models and APIs.

## Database security and rollout

Migration chain: `0071_platform_commerce_documents` → `0072_managed_file_versions` → `0073_subscription_price_snapshot`.

All organization-owned commerce and file tables use forced PostgreSQL RLS and are included in the production readiness RLS allowlist. The plan catalogue also uses RLS: active plans are readable, writes are platform-admin-only.

Run:
1. `alembic upgrade head` using the migration-owner URL.
2. `pytest -q tests/test_platform_commerce.py tests/test_database_security.py`.
3. Full CI, including migration upgrade/downgrade, Python compile, all backend tests and frontend builds.
4. Configure object storage and malware scanning before enabling document uploads.
5. Configure a real payment provider before describing subscription payments as automatically executed.
6. Smoke-test customer tenant boundaries and Superadmin access with separate accounts.
