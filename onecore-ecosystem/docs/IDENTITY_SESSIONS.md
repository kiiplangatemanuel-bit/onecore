# OneCore account sessions and device revocation

## Scope

OneCore now records each newly issued first-party API session as a durable
account-owned record. The signed bearer token contains the matching opaque
session ID (sid); the database stores no bearer token or raw IP address.

Each record captures the account, authentication method, MFA assurance,
optional user-supplied device name, bounded user-agent string, creation time,
last-seen time, expiry and revocation reason. Session rows are protected by
PostgreSQL ENABLE/FORCE ROW LEVEL SECURITY and a user-owner policy. The API
role receives only SELECT, INSERT and UPDATE; session history is not deleted
by the account-facing API.

## API

- GET /api/v1/auth/sessions lists the signed-in account's latest 50 sessions.
- DELETE /api/v1/auth/sessions/{session_id} revokes one of the signed-in
  account's sessions. Attempting to revoke another account's session returns
  404.
- POST /api/v1/auth/sessions/revoke-others revokes all other unexpired
  sessions while preserving the current tracked session.

Revocation is checked against the database on every authenticated API request.
A revoked, expired, deleted or authentication-version-mismatched session is
rejected even if its JWT signature and expiry remain valid. Session creation,
individual revocation and bulk revocation are audited.

Password reset and MFA enablement/disablement revoke all active session rows
and increment the account authentication version. MFA assurance is carried
through the PKCE portal-code exchange; privileged platform roles require the
signed mfa_verified claim rather than merely having an MFA factor enrolled.

## Compatibility and limitations

Tokens issued before session tracking was deployed do not contain a session ID.
They remain subject to their existing JWT expiry and account authentication
version, but cannot be individually revoked or identified in the session list.
Sign in again to obtain a tracked session. No refresh-token family, passkey,
OIDC federation, IP geolocation, device attestation or hardware binding is
claimed. User-agent strings are client supplied and are descriptive only, not
proof of device identity.

The access-token lifetime remains controlled by ACCESS_TOKEN_EXPIRE_MINUTES.
The session expiry is aligned with that configured lifetime. Production
PostgreSQL/RLS rehearsal, security review and user acceptance testing remain
release requirements.

Powered by OneCore Technologies Ltd
