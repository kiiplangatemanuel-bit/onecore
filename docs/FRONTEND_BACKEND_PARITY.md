# OneCore frontend–backend parity standard

**Status:** Required engineering and release standard  
**Applies to:** The central OneCore application and every independently deployable portal  
**Repository:** `kiiplangatemanuel-bit/onecore`

## 1. Non-negotiable principle

Frontend completeness and backend functionality are equal delivery priorities. A module is not complete because its screens render or its frontend build passes. It is complete only when its user-facing workflows are connected to authorized backend operations, persist or retrieve real data where applicable, and pass end-to-end verification.

The 50/50 split is a planning and acceptance principle, not a claim that two separate numerical scores prove quality. Both frontend and backend gates below must pass.

No production screen may present fabricated business metrics, seeded demo records, simulated payment success, or placeholder actions as live functionality. Clearly labelled empty states, examples, previews, and non-production fixtures are acceptable when they cannot be mistaken for production data.

## 2. Required workflow for every module

1. Define the user journeys, public/authenticated boundary, roles, permissions, and acceptance criteria.
2. Inventory each screen, route, form, table, action, filter, export, and notification.
3. Define and document the API contract: method, path, request/response schema, validation, errors, pagination, and idempotency where relevant.
4. Implement backend business rules and persistence using the existing FastAPI and PostgreSQL architecture.
5. Apply authentication, organization membership, tenant context, role/permission checks, audit events, and PostgreSQL RLS as appropriate. A frontend-selected organization ID is context, never proof of authorization.
6. Connect every frontend action and data view to the API. Use shared API client/configuration; do not expose database URLs, service-role keys, provider secrets, or privileged credentials in browser bundles.
7. Implement loading, empty, success, validation, permission-denied, offline, timeout, and retry states. Do not swallow API errors and silently substitute empty or demo data.
8. Test backend behavior, database persistence, authorization and cross-tenant isolation, then test complete browser journeys against the API.
9. Verify migrations, production configuration, CORS/redirect allowlists, deployed frontend/API compatibility, health/readiness and real persisted records in an approved test tenant.
10. Record evidence and unresolved external dependencies. Do not label a module production-ready while a required gate remains unverified.

## 3. Frontend acceptance gate

A module passes only when all applicable items are evidenced:

- All agreed routes and screens exist and are reachable through correct navigation.
- Responsive layouts work on mobile, tablet and desktop.
- Forms have client-side usability validation and rely on server-side validation for correctness.
- Tables, search, filters, sorting, pagination and exports operate on API-backed data where required.
- Create, view, update, submit, approve, reject, cancel and delete actions are implemented only where authorized and supported by the business rules.
- Public visitors can use only explicitly public functions; authenticated views require a valid session.
- Role-aware navigation is consistent with, but never substitutes for, backend authorization.
- Loading, empty, error, offline, retry and success states are present and accessible.
- No dead buttons, fake counters, hard-coded customer records, mock success messages, or production demo data remain.
- Browser console and network requests show no unhandled errors, leaked secrets, or unintended cross-origin calls.

## 4. Backend and data acceptance gate

A module passes only when all applicable items are evidenced:

- API endpoints are documented and use typed request/response validation.
- Business rules, state transitions and approval separation are enforced server-side.
- Reads and writes use the real configured PostgreSQL/Supabase database through the backend.
- Transactions, constraints, foreign keys, indexes and migrations protect data integrity.
- Tenant-owned records carry tenant scope and enforce it in API authorization and PostgreSQL RLS.
- Runtime database roles are least-privilege and do not bypass RLS; production role behavior is rehearsed against the target Supabase project.
- Sensitive actions generate attributable audit events.
- Retries and duplicate submissions are safe; idempotency is implemented for financial/provider operations.
- Secrets remain in server-side secret configuration; external provider failures cannot falsely mark a transaction successful.
- Unit, API, migration, PostgreSQL behavior, permission, cross-tenant and integration tests pass.

## 5. End-to-end proof required

For each module, retain evidence for at least:

1. Public or authenticated entry as appropriate.
2. Successful authorized read from the API and database.
3. Successful create/update/action through the UI.
4. Independent verification that the expected database record/state changed.
5. Rejection of invalid input.
6. Rejection of anonymous or insufficiently privileged access.
7. Cross-tenant read/write denial for tenant-scoped data.
8. Correct behavior for network/API failure and retry.
9. Audit record for sensitive operations.
10. Deployed smoke test against the intended environment.

Use disposable test tenants and safe test data. Do not initiate live payments, statutory submissions, emails, or other external side effects as part of a test unless the provider's sandbox and authorization are explicitly configured.

## 6. Portal-specific requirements

The independently deployable portals share the OneCore identity, API, and database architecture, but each portal must be audited as a real product:

| Portal | Required functional scope |
|---|---|
| Admin / Superadmin | Tenant governance, privileged operations, audit, support and platform health; every privileged action server-authorized |
| Support | Public enquiries/ticket submission, guest ticket access where supported, authenticated ticket history, replies and attachments |
| Status | Public health/incident/maintenance information and authenticated alert preferences; health reachability must not be misrepresented as full monitoring |
| Developers | Documentation, application registration, scoped credentials, webhook configuration, usage and sandbox workflows |
| Documentation | Public published guides plus authenticated organization-specific content where applicable |
| Community | Public content and authenticated posts, comments, groups, profiles and moderation workflows |
| Trust | Public policies/disclosures plus confidential report submission and restricted case handling |
| Events | Public event discovery plus authenticated registration, booking, attendance and payment status where enabled |
| Careers | Public vacancies plus private applicant profiles, applications and recruitment administration |
| Partners | Public partner information/opportunities plus authenticated partner profiles, referrals, leads, agreements and resources |

A shared shell or successful Vite build does not prove that each portal's user journeys are complete. Shared components may be reused, but each portal needs its own route/API/data/permission/e2e coverage.

## 7. Integration and deployment rules

- Browser applications call the shared FastAPI API; they do not connect with database credentials or Supabase service-role keys.
- All portal origins must be explicitly allowlisted in CORS and portal redirect configuration. Do not use wildcard CORS for bearer-token applications.
- Portal SSO must use the approved short-lived, single-use PKCE handoff; never put bearer tokens in redirect URLs.
- Every deployment must verify the frontend's configured API origin, backend health/readiness, migrations, required secrets, deep-link fallback, and public/authenticated access.
- A successful CI build is source validation, not proof of production deployment, live provider connectivity, or user acceptance.
- External integrations must report truthful states such as pending, submitted, provider-confirmed, failed, or reconciled. A staff-entered reference is not proof of provider settlement.

## 8. Module delivery scorecard

Track each module independently with these statuses:

- **Not started:** No reviewed implementation evidence.
- **UI in progress:** Screens exist, but one or more frontend gates remain.
- **API/data in progress:** Backend or persistence exists, but one or more backend gates remain.
- **Integrated:** UI and API are connected; end-to-end acceptance is incomplete.
- **Verified in CI:** Automated frontend, backend, migration and security tests pass in CI.
- **Verified in staging:** Full browser-to-database journeys and tenant/security tests pass in a production-like environment.
- **Production accepted:** Deployed checks, configuration, monitoring, external dependencies and user acceptance are evidenced.

Never infer a higher status from file presence, route presence, a passing build, or a green unit-test suite alone. Record blockers and evidence links for each status transition.

## 9. Current repository audit baseline (13 November 2026)

The repository contains the React/Vite central frontend, a shared portal shell in `frontend/src/PortalApp.jsx`, shared API client in `frontend/src/api.js`, and ten independently buildable Vite portal entry points under `frontend/portals`.

The ten portal `src/main.jsx` files are thin entry points that mount the shared `PortalApp`; they are not ten separately implemented applications. The shared shell already includes public content and authenticated portal workflow areas, and the portal deployment guide documents API-backed record types and endpoints. This is a useful foundation, not proof that every listed workflow is complete.

The central frontend README explicitly identifies some module entries as workspace shells until dedicated screens and API contracts are implemented. The backend implementation tracker also classifies several specialist business applications as partial and documents production configuration, provider, monitoring, backup/restore and UAT gates. These limitations must remain visible in delivery reporting.

At the latest reviewed repository head, `main` was `f7c526ac069558062ab86026f7f2b006280cf1f6`. The implementation tracker reports 471 passing pytest tests and passing migration, dependency-audit, Python compilation, central frontend build and ten portal build checks. Those are CI results only. They do not prove that every screen is API-backed, that the production Supabase runtime role is correctly provisioned, or that the current production deployments are healthy.

Known operational release blockers in the tracker include missing production health-check configuration and missing backup/restore storage/database secrets. Live Supabase role rehearsal, production health/readiness checks, backup/restore drills and external-provider/UAT evidence must be completed before claiming production acceptance.

## 10. Immediate execution order

1. Build a route/screen/action-to-API inventory for the central application and all ten portals.
2. Mark every UI element as public, authenticated, role-restricted, read-only, or mutating.
3. Map each action to its API endpoint, database table/model, tenant rule, permission and audit behavior.
4. Identify screens using placeholder data, workspace shells, unimplemented actions, swallowed errors or missing API contracts.
5. Prioritize shared identity, organization context, permissions and API client gaps first.
6. Complete one end-to-end vertical slice at a time, with frontend and backend work delivered together.
7. Add portal-specific browser tests and database/security assertions to CI.
8. Rehearse against staging Supabase and verify deployment/operations gates before production acceptance.

**Definition of done:** A real user can complete the documented workflow through the deployed frontend; the backend validates and authorizes it; the correct tenant-scoped database state is persisted; unauthorized and cross-tenant attempts are rejected; and the result is independently verified by automated or recorded acceptance evidence.
