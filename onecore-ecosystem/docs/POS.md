# OneCore POS checkout and offline queue foundation

This slice provides cashier shifts, catalogue pricing, checkout, stock deduction and
an encrypted browser transaction queue with idempotent synchronization. It is not
yet a complete 24-hour offline POS or a live payment terminal integration.

## API

- `GET /api/v1/pos/catalog?branch_id={branch_id}`
- `GET /api/v1/pos/shifts/current?branch_id={branch_id}`
- `POST /api/v1/pos/shifts/open`
- `POST /api/v1/pos/shifts/{id}/close`
- `POST /api/v1/pos/sync`

Checkout prices are read from the tenant product catalogue (`sale_price`), not
accepted from the client. The sale API validates an open shift owned by the cashier
at the selected branch, validates tenant product ownership, checks branch stock,
and requires payment allocations to equal the server-calculated total. A sale and
its inventory issue movements, lines and payment records are committed atomically.
Client transaction IDs are tenant-unique; a canonical request hash makes identical
replays idempotent and conflicting reuse return HTTP 409.

Shift close compares counted cash with opening float plus recorded cash tender and
returns the variance. Credit tenders are stored as unsettled. Cash/card/bank are
recorded tender types only; no acquiring gateway, M-Pesa, STK push or bank
verification is connected.

## Browser offline behavior

- POS shell can be cached by the service worker after the first successful visit.
- The last downloaded branch catalogue is encrypted with AES-GCM using a
  non-extractable Web Crypto key stored in IndexedDB.
- Pending transaction payloads are encrypted before IndexedDB persistence.
- Manual and online-event sync sends queued transactions to the idempotent API.
- The browser keeps a local stock snapshot and blocks a sale that exceeds that
  snapshot; the server rechecks stock at sync and rejects stale/oversold transactions.

Offline sale creation requires the page to remain open with a valid in-memory
authenticated session and an open shift. Refreshing the browser loses the access
token; offline login/session restoration is not implemented. The service worker
caches only the POS shell, not private API responses. Browser-profile storage is
not a substitute for managed device encryption, hardware-backed keys or device
attestation.

## Remaining POS requirements

- Offline re-authentication/device registration, local authorization expiry and
  revocation; robust 24-hour offline entitlement.
- Multiple products per cart (server supports multiple lines; current UI submits
  one line), discounts, tax calculations, returns/refunds, receipts and printing.
- Cash drawer, till/device inventory, cashier permissions, multi-user/multi-till
  shift reconciliation and approval thresholds.
- M-Pesa/card/bank gateway integrations, verified callbacks, settlement and
  reconciliation. Manual tender rows are not payment verification.
- Server-side reservation/conflict policy for stale offline stock, supervisor
  review/override and queue dead-letter/retry visibility.
- Background Sync API support, sync telemetry, bandwidth-aware catalogue refresh,
  crash recovery and cross-device/cross-branch reconciliation.
- Full accessibility, threat modelling, browser/device matrix, PostgreSQL race tests,
  performance, security assessment and pilot UAT.
