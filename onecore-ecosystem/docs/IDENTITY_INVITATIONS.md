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

## Email verification and password recovery

- Organization registration creates an inactive account and a one-time email
  verification record. The verification token is stored as a SHA-256 digest and
  expires after 24 hours. Configure SMTP/email settings and the public site URL
  before enabling registration in a deployment.
- `POST /api/v1/auth/password-reset/request` accepts an email address and always
  returns the same generic response for existing, inactive and unknown accounts.
  Active-account reset tokens are random, stored only as SHA-256 digests, expire
  after 30 minutes and supersede earlier unconsumed reset links. Delivery uses the
  configured SMTP integration; failures are logged without exposing account
  existence in the response.
- `POST /api/v1/auth/password-reset/confirm` accepts a token and a new password.
  It locks and consumes the token, updates the password, records an audit event
  and increments the user's authentication version. This invalidates all previously
  issued OneCore API access tokens for that account.
- The workspace exposes `/forgot-password` and `/reset-password` screens.
  Reset tokens are delivered in the URL fragment and removed from the address bar
  before submission, so the browser does not send them to web-server access logs.

## Remaining identity requirements

MFA/TOTP and recovery codes, external OIDC identity federation, durable session
and device inventory, per-session revocation, privileged step-up authentication,
account recovery for unverified users, distributed edge/WAF throttling, and
production email-domain authentication and delivery monitoring remain release
requirements. The current password-reset email sender is synchronous SMTP; a
durable retrying email outbox/worker remains future operational hardening.

## Branch administration

- `POST /api/v1/branches` creates a branch with a tenant-unique code.
- `GET /api/v1/branches` lists only active branches visible to the membership's
  branch scope.
- `PUT /api/v1/branches/{id}` updates branch metadata.
- `DELETE /api/v1/branches/{id}` deactivates a branch without deleting its
  historical records.

Record creation and updates reject branch IDs that do not belong to the active
organization or refer to an inactive branch. Tenant and branch filters are
applied server-side. Branch IDs are UUID strings.

The branch APIs are backend foundations. A dedicated admin frontend, branch
transfer/reassignment workflow, and migration plan for historical branch data
remain outstanding.
