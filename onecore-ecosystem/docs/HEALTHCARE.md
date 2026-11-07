# Healthcare patient registration and appointments

This first healthcare slice provides a minimal tenant-owned patient directory and
appointment scheduling workflow. It does not provide an electronic medical record,
clinical decision support or regulated clinical operations.

## Patient directory
- `POST /api/v1/healthcare/patients` — manager-only patient registration.
- `GET /api/v1/healthcare/patients` — tenant/branch-scoped patient list.
- Patient numbers are unique within an organization. Only basic demographics and
  emergency-contact details are stored in this slice.

## Appointments
- `POST /api/v1/healthcare/appointments` — create an appointment for an existing
  tenant patient; optional provider must be an active member of the same organization.
- `GET /api/v1/healthcare/appointments` — tenant/branch-scoped appointment list.
- `POST /api/v1/healthcare/appointments/{id}/cancel` — manager cancellation.
- `POST /api/v1/healthcare/appointments/{id}/complete` — manager completion.
- Appointment numbers are organization-unique. A provider cannot be assigned two
  overlapping scheduled appointments. Appointment timestamps must be timezone-aware.
- Patient registration and appointment lifecycle changes create audit events.

The `/healthcare` starter workspace supports patient registration, appointment
scheduling, listing, cancellation and completion.

## Explicit limitations
- No clinical encounter notes, diagnoses, allergies, medication, prescriptions,
  procedures, vitals, clinical decision support or electronic medical record.
- No laboratory, imaging, pharmacy, inpatient admission, bed/ward, nursing, theatre,
  insurance claims, billing, discharge, referrals or clinical coding.
- No patient/guardian portal, consent management, identity verification or
  interoperability (HL7/FHIR).
- No role-specific clinician access matrix beyond tenant permissions, emergency
  break-glass controls, encryption/key-management review, retention policy,
  privacy impact assessment, security assessment or UAT.
- No provider schedule templates, room/resource booking, reminders, waitlist,
  recurring visits, appointment rescheduling or telemedicine.

Patient data is sensitive. Complete a Kenya Data Protection Act/privacy review,
health-sector security assessment, access-control review, clinical governance and
user acceptance testing before production use. The starter module is not a clinical
record system.
