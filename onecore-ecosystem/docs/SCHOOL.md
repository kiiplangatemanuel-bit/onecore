# OneCore School Management Foundation

This increment adds a tenant-scoped academic foundation; it is not a complete school
management system and must not be used as a substitute for an institution's approved
student information, statutory reporting or safeguarding processes.

## Delivered

- Academic classes/streams per academic year, optionally scoped to a branch.
- Applicant registration with tenant-unique admission numbers, guardian contact
  fields and an explicit admission transition.
- Tenant-owned CBC subject catalogue.
- Class/subject assessments with maximum score and configurable assessment weight.
- Batch mark entry/update, validation against active class membership and maximum
  score, and immutable marks after publication.
- Organization-configurable grade bands with overlap prevention.
- Controlled publication by a member with organization manage permission.
- Published assessment results with grade and competition ranking (ties share rank).
- Weighted term report-card summaries from published assessments.
- Daily attendance registers with present, absent, late and excused statuses; duplicate
  learner rows are rejected, entries can be corrected for the same learner/date, and
  every batch is audited. Learners must be active and enrolled in the selected class.
- Audit events for admissions, admission, class/subject/assessment creation, mark
  entry, grade-band configuration, publication and attendance recording.
- Migrations `0007_school` and `0013_school_attendance`, API routes under
  `/api/v1/school`, basic workspace at `/school`, and automated model/schema/OpenAPI tests.

## API

- `GET/POST /api/v1/school/classes`
- `GET /api/v1/school/learners`
- `POST /api/v1/school/attendance` (batch upsert by learner and date)
- `GET /api/v1/school/attendance?class_id=1&attendance_date=2026-11-07`
- `POST /api/v1/school/admissions`
- `POST /api/v1/school/learners/{id}/admit`
- `GET/POST /api/v1/school/subjects`
- `GET/POST /api/v1/school/assessments`
- `PUT /api/v1/school/assessments/{id}/marks`
- `POST /api/v1/school/grade-bands`
- `POST /api/v1/school/assessments/{id}/publish`
- `GET /api/v1/school/assessments/{id}/results`
- `GET /api/v1/school/classes/{id}/report-cards?term=Term%201`

All endpoints use active organization membership. Class, learner and assessment
records are tenant-scoped; branch-scoped operations check membership branch access.
Only active learners in the assessment's class may receive marks. Publication
requires manage permission and locks subsequent mark changes.

## Explicit gaps

- Full admissions application/review, document uploads, guardian/teacher/staff
  records, class promotion, attendance notifications/analytics, timetable, curriculum/learning areas,
  CBC strands/outcomes, lesson plans and learning resources.
- Configurable weighted subject aggregation beyond the delivered assessment-weight
  report calculation; term/year grading, grade transitions, moderation, remarking,
  approvals and report-card PDF/transcript generation.
- Tie rules beyond competition ranking, configurable rank groupings (class/stream/
  form/grade), merit lists and publication audience controls.
- Fees, invoicing, receipts, bursaries, boarding, transport, library, discipline,
  health records, parent/learner portals, e-learning and communication.
- Finance integration, M-Pesa collections, statutory data exchange, analytics,
  accessible bilingual full UI, PostgreSQL concurrency testing, security review,
  safeguarding review, performance and pilot UAT.
- The current workspace is a starter administration UI. No guardian portal or
  production deployment is claimed.


## Attendance increment — 7 November 2026

The first attendance slice provides a daily class register. `POST /api/v1/school/attendance`
accepts a class, date and batch of learner status entries. Posting validates tenant and
branch access, requires every learner to be active in that class, rejects duplicate
learner IDs in the submitted batch, and upserts a learner's entry for that date. A
learner cannot be moved between classes by a register update. `GET` retrieves the
register for an authorized class/date. The database unique index prevents duplicate
records for a tenant/date/learner. Migration `0013_school_attendance` is reversible.

Tests added: status and duplicate validation, model table contract and OpenAPI route
registration. The attendance increment does not yet include period-by-period attendance,
excused absence approval, guardian notifications, attendance thresholds, analytics,
biometric/device integrations, bulk CSV import or guardian notifications. The `/school` workspace now includes a
class/date register loader, status and note controls, and batch save. It is a basic
staff interface; role-specific approval and parent-facing workflows are not included. CI must
pass the full migration downgrade/upgrade and pytest workflow before this increment is
considered verified.


## Learner promotion and transfer history increment

The learner placement workflow now supports controlled academic-year promotion and
class/branch transfer:

- `POST /api/v1/school/learners/{learner_id}/placements` requires organization
  manage permission, an active learner, an existing source placement and an active
  target class.
- Promotion requires a strictly later academic year. Transfers can move between
  parallel classes in the same year or into a later year; moving backwards in the
  academic calendar is rejected.
- The actor must have access to both source and target branches. The learner's
  current class and branch are updated in the same database transaction that writes
  the append-only placement history and audit event.
- `GET /api/v1/school/learners/{learner_id}/placements` returns chronological
  history with source/target class and year details, subject to access to both
  branches represented in the history.
- Placement history is retained rather than overwriting the previous class link. The `/school` workspace includes a placement form and chronological history viewer.
  Existing attendance rows remain associated with the class in which they were
  originally recorded.

This increment does not implement class capacity/waitlists, guardian consent,
bulk promotion, promotion eligibility rules, transcript migration, fee carry-forward,
or notifications. Effective dates are recorded as administrative history; the API
does not backdate historical attendance or assessment membership. Review the school's
approved promotion policy and safeguarding procedures before production use.


## Advanced School workflow increment — 8 November 2026

The advanced workflow API is registered from `app/api/school_advanced.py` and is
available under `/api/v1/school`. It reuses the existing tenant-owned Record store
for configurable workflow documents and the existing School learner, class,
assessment, mark and enrollment-history tables for core academic entities.

Delivered in this increment:

- Ranking configuration by academic year, optional class and subject, grouping,
  tie method and tie-breaker settings; weighted published-assessment ranking output.
- Draft examination timetables, date/time sessions, publish transition and seating
  plans with duplicate seat/learner rejection and active class-roster validation.
- Assessment moderation decisions with moderator identity and mark references.
- CBC curriculum nodes covering grade, learning area, strand, sub-strand, outcome
  code, outcome description and indicators; learner competency evidence and level.
- Bulk promotion/transfer with active source-class membership checks, year-direction
  rules, explicit skip-ineligible behavior and append-only canonical enrollment history.
- Fee charges, payment receipt with idempotency key, guarded allocation against
  outstanding learner charges, learner statements, arrears and reconciliation totals.
- Guardian-user links with explicit per-learner academic/fees/attendance/communications
  permissions; guardian portal responses include only linked learners and permitted data.
- Teacher and staff portals based on linked staff profiles and assigned classes.
- Report-card draft, submit, approve/reject and publish states.
- Downloadable JSON transcripts with SHA-256 digest in the response header.
- In-app guardian notification queue and school dashboard/reconciliation summaries.
- Narrow teacher and guardian organization roles; guardian portal access additionally
  requires an explicit guardian-to-learner link.

New endpoints include:

- `GET/PUT /api/v1/school/advanced/ranking-config`; `GET /api/v1/school/rankings`
- `GET/POST /api/v1/school/exam-timetables`; `POST /api/v1/school/exam-sessions`
- `POST /api/v1/school/exam-timetables/{id}/publish`; seating plan under
  `/api/v1/school/exam-timetables/{id}/sessions/{index}/seating`
- `POST /api/v1/school/assessments/{id}/moderation`
- `GET/POST /api/v1/school/curriculum/nodes`; `POST /api/v1/school/competencies`
- `POST /api/v1/school/promotions/bulk`
- `POST /api/v1/school/fees/charges`; `POST /api/v1/school/fees/payments`;
  `POST /api/v1/school/fees/payments/{id}/allocate`;
  `GET /api/v1/school/fees/learners/{id}/statement`
- `POST /api/v1/school/guardians/links`; `GET /api/v1/school/guardian/portal`
- `POST /api/v1/school/staff/profiles`; `GET /api/v1/school/teacher/portal`;
  `GET /api/v1/school/staff/portal`
- `POST /api/v1/school/report-cards`; submit and decision endpoints;
  `GET /api/v1/school/transcripts/{learner_id}`
- `POST /api/v1/school/notifications`; `GET /api/v1/school/dashboard`;
  `GET /api/v1/school/reconciliation`

Verification boundary: the PR adds schema and OpenAPI regression tests and triggers the
repository CI workflow. It must not be called complete or production-ready until the
latest PR-head checks pass and the review closes any security findings.

Known follow-up integration work: notification records are queued in-app; external
SMS/WhatsApp/email delivery requires configured adapters. The transcript is a
downloadable JSON export with integrity digest, not a digitally signed PDF. Fees are
tracked and reconciled inside the School ledger; automated posting to the general
ledger, M-Pesa provider callbacks/refunds, bursaries and bank reconciliation are
separate integrations. Full browser workflows, safeguarding review, PostgreSQL
concurrency tests and school pilot UAT remain required before production use.
