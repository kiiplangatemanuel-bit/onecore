# Secure Files Centre

Master specification category: **57**

## Implemented foundation
Tenant-scoped private file/folder metadata, S3-compatible private object storage, mandatory ClamAV scan before upload, classification-aware access, SHA-256 integrity metadata, immutable file version history, short-lived signed downloads, expiring download-limited share tokens, revocation and soft deletion are implemented.

Uploads fail closed unless private object storage and malware scanning are configured. Private object bucket credentials remain server-side. The database stores metadata/object keys, not file contents.

## Remaining scope
Advanced preview/conversion, full retention schedules, legal holds, electronic signatures, recipient identity restrictions, malware re-scan orchestration, automated data-loss prevention and comprehensive restore drills remain to be implemented.

See `onecore-ecosystem/docs/PLATFORM_COMMERCE_AND_ADMIN.md` for environment requirements and API routes.
