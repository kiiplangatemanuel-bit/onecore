# OneCore Healthcare — patient and clinic workflow

This is the first clinic workflow slice. It provides a tenant-scoped patient register,
appointment scheduling, check-in and signed encounter records. It is not a full
hospital information system and does not replace clinical judgement or local health
records compliance obligations.

## Patient registration

- `POST /api/v1/healthcare/patients` registers a patient using a tenant-unique
  patient number.
- `GET /api/v1/healthcare/patients` lists/searches patients visible in the user's
  branch scope.
- `GET /api/v1/healthcare/patients/{patient_id}` returns an individual patient.
- Patient fields are intentionally limited to patient number, name, date of birth,
  contact details, branch and optional emergency contact. National IDs and payment
  card data are not collected.

## Appointment scheduling

- `POST /api/v1/healthcare/appointments` schedules an appointment for a patient
  and an active organization provider.
- `GET /api/v1/healthcare/appointments` lists appointments with optional status
  and time-window filters.
- `POST /api/v1/healthcare/appointments/{appointment_id}/status` supports
  scheduled → checked-in/cancelled/no-show and checked-in → completed/cancelled.
- All times are required to be timezone-aware and are stored/returned in UTC.
- Appointment creation rejects past times and checks overlapping active bookings
  for both the provider and patient.
- Provider branch scope is checked against the selected appointment branch.

A visit cannot be marked completed until its clinical encounter has been signed.
Cancellation and no-show transitions require a reason.

## Clinical encounters

- `POST /api/v1/healthcare/appointments/{appointment_id}/encounter` opens one
  draft encounter after the patient is checked in. Only the assigned provider can
  create it.
- `GET /api/v1/healthcare/appointments/{appointment_id}/encounter` retrieves the
  encounter with an access audit event.
- `POST /api/v1/healthcare/encounters/{encounter_id}/sign` signs and locks the
  encounter. Only the assigned provider can sign it.
- One encounter per appointment is enforced by a unique database index.
- Signed encounters are immutable through the current API.

## Security and production boundaries

Every endpoint requires active organization membership and the current coarse
`manage` permission. Patient/appointment/encounter queries are tenant-scoped and
branch-checked; reads and changes create audit events. Clinical note content is
stored in the application database. This increment does not implement field-level
encryption, clinician-specific permission roles, patient consent/portal access,
retention and deletion policy, record export, medical-device integration, emergency
access/break-glass workflow or a full privacy/security assessment.

Provider and patient overlap checks use transactional row locks and database
queries, but no PostgreSQL exclusion constraint or serializable-concurrency proof
is included yet. Concurrent scheduling requires production database stress tests.

Not included: inpatient admission/bed management, triage, diagnoses/catalogue,
prescriptions, pharmacy dispensing/batches/expiry, laboratory test catalogue,
sample chain-of-custody, result validation, imaging, billing/insurance claims,
clinical decision support, referral management, discharge summaries, e-prescribing,
KMPDC/health-system integration, FHIR/HL7 exchange, SMS reminders or UAT. Do not
store live patient records until the required privacy, security, retention and
clinical governance controls have been reviewed and approved.
