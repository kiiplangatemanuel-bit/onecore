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
  issued OneCore API access tokens and consumes outstanding cross-portal handoff codes for that account.
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


## Multi-factor authentication (TOTP)

The account-security screen supports TOTP authenticator enrollment, single-use recovery
codes, recovery-code rotation and MFA disablement. The API contract is:

- GET /api/v1/auth/mfa/status reports whether TOTP is enabled and how many
  recovery codes remain; it never returns the stored seed.
- POST /api/v1/auth/mfa/enroll requires the current password and creates a
  ten-minute pending enrollment. It returns the TOTP seed and otpauth URI
  once for manual entry into an authenticator app.
- POST /api/v1/auth/mfa/confirm verifies a current six-digit TOTP and enables
  MFA. Ten one-time recovery codes are returned once. Enabling MFA increments
  the authentication version and consumes outstanding portal authorization
  codes, so existing access tokens must be replaced by signing in again.
- Password login for an MFA-enabled account returns a five-minute challenge
  instead of an access token. POST /api/v1/auth/mfa/challenge accepts a TOTP
  or unused recovery code. Challenges expire, are single-use, allow at most
  five failed attempts and are stored only as SHA-256 digests.
- POST /api/v1/auth/mfa/recovery-codes/rotate and
  POST /api/v1/auth/mfa/disable require password re-authentication and a
  current TOTP or unused recovery code. Rotation revokes previous codes.
  Disablement increments the authentication version and consumes outstanding
  portal authorization codes.

TOTP seeds are encrypted at rest with a dedicated Fernet key. Configure
MFA_ENCRYPTION_KEY in the deployment secret manager using a fresh key generated
with Fernet.generate_key(). MFA enrollment fails closed with HTTP 503 when
the key is absent or invalid; do not use a shared development key in production.
Losing or rotating this key without first re-encrypting enrolled seeds requires
users to re-enroll. Keep the key backed up under the same access controls as
other authentication secrets.

TOTP is RFC 6238 with SHA-1, six digits, a 30-second step and one step of
clock drift in either direction. A successful TOTP step cannot be replayed.
After confirming enrollment, the next sign-in must use a fresh TOTP time-step.
Recovery codes are random 64-bit values displayed in four-character groups;
only SHA-256 digests are stored. The challenge endpoint is protected by the
public-write rate limiter and an additional five-attempt per-challenge limit.

MFA is an optional account-level control in this increment. It is not an OIDC
identity provider, a replacement for organization/branch RBAC, or proof of
provider/production security certification. Hardware security keys, passkeys,
enforced MFA policy by role/tenant, privileged step-up for individual actions,
durable session/device inventory and distributed WAF throttling remain open.
