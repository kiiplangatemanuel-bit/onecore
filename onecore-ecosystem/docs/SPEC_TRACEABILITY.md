# Master specification traceability

The full 75-category register is preserved in `app/modules/catalog.json` and served from `GET /api/v1/modules`. This register is the scope index, not evidence that every category is implemented. The master specification also defines:
- the five architecture pillars and recommended modular-monolith approach
- the domain URL map (`onecore.co.ke`, `app`, `admin`, `developers`, `docs`, `support`, `status`, `files`, `partners`, `community`, `careers`, `trust`, `api`, `auth`, `search`, `media`, `cdn`, `events`)
- public lead/sales, customer registration/onboarding, organization administration and daily work flows
- Superadmin release, maintenance and incident processes
- cross-module sale-to-accounting/tax, school assessment/fees, hospital/SHA claim, SACCO loan, HR/payroll, e-commerce, subscription, support/incident workflows
- external integration controls for M-Pesa, KRA eTIMS, SHA/DHA AfyaLink, banks, messaging, AI and hardware
- domain management, mandatory footer attribution and global maintenance notice requirements in the addendum

The full supplied DOCX remains the authoritative source for detailed acceptance criteria. This starter deliberately does not mark any category as production-complete.
