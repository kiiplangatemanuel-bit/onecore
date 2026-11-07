# Healthcare privacy and access controls

## Data protection
Patient profile JSON and clinical encounter notes are encrypted with Fernet
authenticated encryption before database persistence. Configure
`HEALTHCARE_PHI_ENCRYPTION_KEY` with a dedicated Fernet key before registering
patient data. Generate a key with:
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Store it in a secret manager, restrict access, back it up securely and do not commit
it. Changing the key without a planned decrypt/re-encrypt rotation makes existing
records unreadable. The service returns 503 rather than storing PHI when the key is
missing or invalid. Healthcare API and UI responses use no-store cache headers.

The encryption protects patient profile and clinical note payloads at the
application layer. It does not replace TLS, encrypted database/storage volumes,
encrypted backups, access-controlled logs, key rotation, or a full data lifecycle
policy. Patient MRN and appointment metadata remain indexed plaintext identifiers.

## Healthcare roles
Healthcare roles are separate from generic organization roles and are assigned
by an organization or branch administrator:
- healthcare_admin: full patient, clinical, consent, access and audit administration
- clinician: patient read, clinical read/write, appointments and break-glass
- nurse: patient read, clinical read, appointments and break-glass (no clinical write)
- receptionist: patient registration/read and appointment management (no clinical notes)
- privacy_officer: patient access/consent governance and access audit, without PHI read
- clinical_auditor: patient/clinical read with a recorded reason and audit access
- lab_technician and pharmacist: limited patient/clinical read

Branch admins can assign only branch-scoped operational roles and cannot assign
healthcare_admin, privacy_officer or clinical_auditor. Every request checks active
organization membership and branch scope. Generic org_admin membership alone does
not grant access to patient data; a healthcare role is required.

## Patient-specific grants
Patient detail, update and clinical access require a matching active care-team grant
unless the user is a healthcare_admin or has an active emergency session. Grants
specify read/write access, grantee, grantor, reason, expiry and revocation. The
target user must be an active organization member within the patient branch.
Revocation and expiry are checked on each request.

## Consent
Consent decisions are append-only and support treatment, data_processing,
data_sharing, research and marketing purposes. Each record includes decision,
evidence reference, notes, expiry and recording user/time. The latest decision
controls. New clinical encounter creation and signing/closing require current
treatment consent unless an authorized break-glass session is active. Consent
withdrawal does not erase prior clinical history.

## Emergency access
Only healthcare administrators, clinicians and nurses can open a patient-specific
break-glass session. A reason of at least 15 characters is required. Sessions expire
after 15 minutes and can be closed earlier. Every emergency PHI read/write is marked
in the access audit with the emergency flag and justification. Emergency access
does not bypass tenant or branch boundaries.

## Audit and immutability
Patient reads, updates, access grants/revocations, consent changes, encounters,
appointments and emergency access create healthcare access audit events. Only
healthcare administrators, privacy officers and clinical auditors can read audit
records, filtered by their branch scope. Encounter notes are immutable after closure
through the exposed APIs. The audit API is read-only.

## Main endpoints
- POST/GET /api/v1/healthcare/access/roles; POST /access/roles/{id}/revoke
- POST/GET /api/v1/healthcare/patients
- GET/PUT /api/v1/healthcare/patients/{id}
- POST/GET /api/v1/healthcare/patients/{id}/access; POST /access/{grant_id}/revoke
- POST/GET /api/v1/healthcare/patients/{id}/consents
- POST /api/v1/healthcare/patients/{id}/break-glass; POST /break-glass/{id}/close
- POST /api/v1/healthcare/patients/{id}/appointments
- POST/GET /api/v1/healthcare/patients/{id}/encounters; POST /encounters/{id}/close
- GET /api/v1/healthcare/audit

## Governance and release boundary
These controls are technical safeguards, not a claim of legal certification or
complete compliance with the Kenya Data Protection Act, Digital Health Act,
professional practice rules or other jurisdictions. Production readiness still
requires key rotation/recovery procedures, MFA/step-up for privileged users,
retention/deletion and data-subject request workflows, legal-hold rules, TLS,
database/backup encryption, penetration testing, security monitoring, clinical
governance review and live UAT.
