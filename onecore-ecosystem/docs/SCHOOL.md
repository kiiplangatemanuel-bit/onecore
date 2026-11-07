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
- Audit events for admissions, admission, class/subject/assessment creation, mark
  entry, grade-band configuration and publication.
- Migration `0007_school`, API routes under `/api/v1/school`, basic workspace at
  `/school`, and automated model/schema/OpenAPI route tests.

## API

- `GET/POST /api/v1/school/classes`
- `GET /api/v1/school/learners`
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
  records, class promotion, attendance, timetable, curriculum/learning areas,
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
