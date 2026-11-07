# CRM campaign automation and healthcare privacy

## CRM automation

- Reusable tenant-owned email, SMS and WhatsApp templates are managed through
  /api/v1/crm/templates. Templates support only allowlisted placeholders:
  {{first_name}}, {{full_name}}, {{company}}, {{email}}, {{phone}}.
- Saved audience segments use a validated JSON DSL with all/any groups, approved
  contact fields, lead stage/source/value and eq/neq/contains/in/gte/lte operators.
  SQL is always parameterized; field names and operators are allowlisted.
- Campaigns can apply a template and saved segment while in draft. Preparation
  snapshots only contacts with current channel/purpose consent; dispatch rechecks
  consent immediately before sending. Personalized values are rendered at dispatch.
- Schedule only after preparing a campaign. POST /api/v1/crm/campaigns/{id}/schedule
  requires a future timezone-aware timestamp. Configure CRM_SCHEDULER_SECRET and
  call POST /api/v1/crm/scheduler/run from a trusted scheduler (e.g. a cron job or
  managed task) with X-CRM-Scheduler-Secret. The worker processes due campaigns in
  batches of 100; call it repeatedly until each scheduled campaign completes.
  Schedule processing is not active until this deployment secret and scheduler
  invocation are configured.

## Healthcare privacy and access controls

- Patient direct identifiers are encrypted with Fernet before persistence. Configure
  HEALTHCARE_DATA_ENCRYPTION_KEY with a generated Fernet key and keep it in a secret
  manager; losing or rotating the key without a planned re-encryption process makes
  existing patient identifiers unreadable. Patient numbers are stored as keyed
  digests for duplicate detection, not as plaintext.
- Patient access is deny-by-default. A clinical user must have an active membership
  in the same organization, an approved clinical/health-records role, branch scope,
  and a non-expired patient-specific grant. Grants are revocable, time-limited to
  at most 365 days, and separately scoped read/write/clinical.
- Patient consent decisions for treatment, billing, disclosure, research and
  telehealth are append-only records with optional expiry. Access authorization is
  not inferred from a general consent record; treatment and other legal bases must
  be assessed under applicable law and organization policy.
- Emergency break-glass access requires a clinical role, a reason of at least 20
  characters, and expires within 60 minutes. Every patient read, registration,
  grant, revoke, consent operation and emergency event is audited. A privacy officer
  or administrator must independently review emergency access; self-review is
  prohibited.
- Access-audit and consent registers are restricted to privacy/admin roles. No
  generic organization-wide patient search or wildcard clinical access is exposed.

Deployment/security boundaries: encryption-key custody/rotation, TLS, database and
backup encryption, database least privilege, log retention, tested restore, incident
response, DPIA, clinical role assignment, patient-rights workflows, jurisdiction-
specific legal review (including Kenya's Data Protection Act and health-data rules),
penetration testing and production clinical UAT remain required. These code controls
are a security foundation, not a claim of statutory certification or perfect safety.
