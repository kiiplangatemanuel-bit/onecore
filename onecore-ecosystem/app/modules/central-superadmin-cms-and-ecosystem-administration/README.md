# Central Superadmin CMS and Ecosystem Administration

Master specification category: **62**

## Implemented platform administration foundation
The authenticated `/superadmin` control surface now supports live platform overview, organization listing and suspension/reactivation, user listing and suspension/reactivation, subscription plans, subscription payment review, subscription monitoring, platform notices and audit history.

These controls are backed by protected FastAPI endpoints, durable database records and audit events. Platform user suspension increments the authentication version. Root Superadmin suspension is intentionally blocked from the general endpoint.

## Remaining scope
This is not the full CMS/operations scope. Public portal content management, media/SEO/translations, maintenance windows, incident command, release management, platform security policy administration, tenant provisioning automation, data export, advanced monitoring and high-risk dual-approval workflows still require domain models, APIs, migrations, tests and UI.

See `onecore-ecosystem/docs/PLATFORM_COMMERCE_AND_ADMIN.md` for endpoint and security details.
