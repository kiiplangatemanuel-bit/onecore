# Identity, invitations and tenant administration

## Organization invitations

All invitation endpoints require an authenticated account. Management endpoints
also require the membership's `manage` permission.

- `POST /api/v1/invitations` creates a seven-day invitation. Supply email, role
  and branch scope. The raw token is returned once; only its SHA-256 digest is
  stored. Deliver the token through a configured secure email provider.
- `GET /api/v1/invitations` lists invitation state without exposing token hashes.
- `POST /api/v1/invitations/accept` accepts a token only when the signed-in
  account email matches the invited email. Expired, revoked, used and mismatched
  invitations are rejected.
- `DELETE /api/v1/invitations/{id}` revokes an unaccepted invitation.

Allowed invitation roles are `org_admin`, `branch_admin`, `manager`,
`accountant`, `staff` and `viewer`. Unknown roles deny permissions. The
branch-scope field currently accepts `*` or a comma-separated list of branch
identifiers; a dedicated Branch entity and branch administration UI remain
required before this can be treated as complete branch management.

## Remaining identity requirements

Email verification and delivery, password recovery, MFA/TOTP and recovery codes,
SSO/OIDC, session/device inventory and revocation, rate limiting, login
throttling, and production account provisioning are not implemented by these
invitation endpoints. They remain release blockers for production identity.
