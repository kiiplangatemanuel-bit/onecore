# Account multi-factor authentication

## Security design

OneCore supports optional account-level TOTP using RFC 6238 (SHA-1, six digits,
30-second period and one-step clock drift). The TOTP seed is encrypted at rest
with a dedicated Fernet key. The API refuses enrollment when the key is absent
or malformed; it never falls back to plaintext or to the healthcare PHI key.

Generate a fresh key with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Store the output in the deployment secret manager as MFA_ENCRYPTION_KEY.
Do not commit it. Back it up securely. Losing or rotating the key without a
re-encryption process requires affected users to enroll again.

## Privileged platform policy

The platform enforces MFA before granting an ordinary API session to
root_superadmin, platform_admin, security_admin, cms_admin, support_admin,
developer_api_admin, maintenance_admin, incident_commander, release_manager,
analytics_admin and recruitment_admin accounts. A password or Supabase Auth
session without an accepted second factor receives a restricted MFA-enrollment
token that expires within ten minutes. That token is accepted only by the
status, enrollment and confirmation endpoints; it cannot call /auth/me, tenant
APIs, platform administration APIs or other protected routes. Enrollment
confirmation increments auth_version, so the restricted token is invalidated
immediately.

A Supabase Auth session may satisfy the policy only when the configured
Supabase Auth service has validated the supplied token and the verified JWT
assurance claim is aal2. A local OneCore TOTP factor also satisfies the
policy after the normal MFA challenge succeeds. Ordinary customer accounts
retain optional MFA unless an organization policy is added.

## User flows

1. An authenticated user opens Account security and re-enters the current
   password to begin enrollment.
2. The API returns a pending secret and otpauth URI for manual entry into an
   authenticator app. The pending setup expires after ten minutes.
3. The user confirms with a current six-digit code. The API enables MFA,
   increments the account authentication version, invalidates existing access
   tokens and consumes outstanding portal handoff codes. The next login must
   use a fresh TOTP time-step; the enrollment code cannot be replayed.
4. Ten one-time recovery codes are displayed once. Only their SHA-256 digests
   are stored. Each recovery code is consumed once; rotation revokes prior
   unused codes and returns a fresh set.
5. Password login for an MFA-enabled account returns a five-minute challenge.
   The challenge is stored as a digest, allows five failed attempts and is
   consumed on successful verification. The last accepted TOTP time-step is
   stored to prevent replay across challenges.
6. Disablement requires password re-authentication and a current TOTP or
   unused recovery code. It increments the authentication version and revokes
   outstanding portal authorization codes.

## API

- GET /api/v1/auth/mfa/status
- POST /api/v1/auth/mfa/enroll
- POST /api/v1/auth/mfa/confirm
- POST /api/v1/auth/mfa/challenge
- POST /api/v1/auth/mfa/recovery-codes/rotate
- POST /api/v1/auth/mfa/disable

The account-security screen is available at /account/security. The sign-in
screen automatically requests the second factor after password verification.

## Operational limitations

Mandatory MFA currently covers the platform roles listed above. New
privileged staff roles must be added to the same policy before they are assigned
to users or granted access.
Organization-level and custom role-level policies, passkeys/WebAuthn, external
OIDC federation, privileged step-up for individual financial/admin actions,
durable per-device session inventory and distributed WAF throttling remain
outstanding. The key must be managed and rotated through a separately reviewed
procedure. Set MFA_ENCRYPTION_KEY in the secret manager before privileged users
enroll, and test the workflow with the production authenticator fleet and
supported devices before enabling it for customers.
