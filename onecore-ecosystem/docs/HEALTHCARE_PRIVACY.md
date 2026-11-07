# OneCore Healthcare privacy and access controls

## Scope and operating requirements
This privacy layer adds encrypted patient identity and clinical encounter storage,
healthcare-specific roles, patient-level grants, append-only consent decisions,
time-limited emergency access and a dedicated access audit trail. It is not a
certification of compliance with the Kenya Data Protection Act, the Digital Health
Act, professional practice requirements or any other jurisdiction's rules.

Before storing live patient data, configure a strong `SECRET_KEY` and a
separately managed Fernet `HEALTHCARE_ENCRYPTION_KEY`. The key must be backed
up securely and access-restricted. If no dedicated key is configured, a
domain-separated key is derived from SECRET_KEY for development; the unsafe default
secret key is rejected. Key rotation requires a controlled re-encryption migration
and must not be performed by simply replacing the key.

## Role separation
Healthcare role assignments are separate from generic organization roles and are
branch-scoped:
- healthcare_admin: full patient, clinical, consent, access and audit administration
- clinician: patient read, clinical read/write, appointment management and emergency access
- nurse: patient read, clinical read and appointment management (no clinical write)
- receptionist: patient registration/read and appointment management (no clinical notes)
- privacy_officer: consent/access governance and audit review, without patient record read
- lab_technician / pharmacist: limited patient and clinical read (workflow-specific controls remain required)

Organization admins assign organization-wide roles. Branch admins may assign only
branch-scoped non-privileged roles. Role revocation is audited. Active organization
membership and branch scope are checked on every API request.

## Patient-level access and consent
Clinical and patient detail reads require an explicit, unexpired patient access grant
for the requested permission, unless the user is a healthcare administrator or has
an active emergency session. Grants record who granted access, why, permissions,
expiry and revocation. Grant revocation takes effect on the next request.

Treatment, data-processing, sharing, research and marketing consent decisions are
append-only. The newest decision for a purpose controls new clinical writes.
Clinical encounter creation/signing requires current treatment consent unless a
valid break-glass session is active. Revoked consent does not erase clinical history.

## Emergency access
Only healthcare administrators, clinicians and nurses may open a break-glass session.
A justification of at least 15 characters is mandatory; sessions expire after 15
minutes and can be closed earlier. Every emergency read/write is marked in the
healthcare access audit. Emergency access does not grant organization or branch
scope beyond the caller's active membership.

## Encryption and audit
Patient names, dates of birth, contact and emergency-contact fields are stored in
authenticated Fernet ciphertext. Clinical complaint, notes, assessment and plan are
stored in a separate authenticated ciphertext blob. Ciphertext is never returned
without passing role, branch and patient-grant checks. Healthcare access audit
records actor, patient, action, resource, reason and emergency flag, but deliberately
does not copy clinical text or patient identity into audit details. Access audit is
available only to privacy officers and healthcare administrators, filtered by
their branch scope. Clinical encounters are immutable after signing through these APIs.

## APIs
- POST /api/v1/healthcare/access/roles and POST /access/roles/{id}/revoke
- POST /api/v1/healthcare/patients
- GET /api/v1/healthcare/patients and GET /patients/{id}
- POST /api/v1/healthcare/patients/{id}/access-grants and POST /access-grants/{grant_id}/revoke
- POST/GET /api/v1/healthcare/patients/{id}/consents
- POST /api/v1/healthcare/patients/{id}/break-glass and POST /break-glass/{id}/close
- POST /api/v1/healthcare/patients/{id}/appointments
- POST/GET /api/v1/healthcare/patients/{id}/encounters
- POST /api/v1/healthcare/encounters/{id}/sign
- GET /api/v1/healthcare/audit

## Boundaries requiring deployment and governance work
Production key management/rotation, TLS termination, backups, retention/deletion and
legal-hold schedules, patient data-subject request workflows, MFA/step-up authentication,
database-level encryption, monitoring/alerting, penetration testing, PostgreSQL
concurrency tests, clinical governance review and production UAT remain deployment
requirements. No live provider or clinical data has been used in CI.
