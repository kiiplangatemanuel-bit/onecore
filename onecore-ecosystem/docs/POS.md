# OneCore POS checkout, receipts and controlled returns

The POS foundation supports cashier shifts, catalogue pricing, multi-line sale
synchronization, stock deduction and an encrypted browser transaction queue. This
delivery adds tenant-scoped sale receipt retrieval and supervisor-authorized partial
returns. It is not a complete 24-hour offline POS or a live payment terminal.

## Checkout and offline synchronization

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

## Sale receipts and returns

- `GET /api/v1/pos/sales/{sale_id}` returns a tenant- and branch-scoped receipt
  payload, including original sale lines, payment tender records and remaining
  returnable quantity for each line.
- `POST /api/v1/pos/sales/{sale_id}/returns` records a partial or full return.
  The caller must hold the tenant `manage` permission (supervisor/manager).
- A return can only reference lines from the original posted sale. Quantities already
  returned are aggregated and a new return cannot exceed the remaining sold quantity.
- Refund allocations must equal the server-calculated return value and cannot exceed
  the remaining recorded original tender for each refund method. Unsettled credit
  tender is not treated as collected funds.
- Return stock is added through append-only inventory receipt movements in the
  original sale branch. Return IDs are tenant-unique and canonical request hashes
  protect safe retries; conflicting reuse returns HTTP 409.
- Refund rows are accounting records only. `refunds_executed=false` is returned
  because cash drawer payout or card/bank/M-Pesa gateway execution is not automated.
- Return valuation uses the original stored sale line unit price. POS tax allocation,
  discount allocation and accounting journal integration are not yet implemented.

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

- Customer accounts, receipt rendering/thermal printing and cash drawer integration.
- Offline re-authentication/device registration, local authorization expiry/revocation
  and a robust 24-hour offline entitlement.
- Discounts, tax calculation, customer accounts, receipt rendering/thermal printing
  and cash drawer integration.
- Cashier permissions, multi-user/multi-till shift reconciliation and approval
  thresholds beyond the manager permission on returns.
- M-Pesa/card/bank gateway integrations, verified callbacks, settlement and
  reconciliation. Manual tender/refund rows are not payment verification/execution.
- Server-side stock reservations, supervisor review of stale offline stock conflicts,
  queue dead-letter/retry visibility, background sync and sync telemetry.
- Bandwidth-aware catalogue refresh, crash recovery, cross-device/cross-branch
  reconciliation, accessibility, threat modelling, browser/device matrix,
  PostgreSQL race tests, performance, security assessment and pilot UAT.


## Product tax and controlled POS discounts

Product tax is configured on the tenant-owned inventory product using `tax_rate` (percentage, 0–100). The POS catalogue exposes this configured rate; the client cannot choose or override it at checkout. The rate is snapshotted on every posted sale line so later product tax edits do not rewrite historic receipts.

Checkout supports a per-line `discount_percent` (0–100). Any non-zero discount requires the caller's `manage` permission; ordinary cashier checkout remains available with zero discount. Offline request hashes include the discount percentage, preventing a queued transaction ID from being replayed with different discount terms.

Calculation order is explicit:
1. Gross line subtotal = rounded unit price × quantity.
2. Discount = rounded subtotal × discount percentage.
3. Taxable base = subtotal − discount.
4. Tax = rounded taxable base × product tax rate.
5. Line total = taxable base + tax.

Sale headers and receipt responses include subtotal, discount, tax and final total. Each sale line stores its original tax and discount snapshot.

Partial and full returns now use the original tax-inclusive discounted line value rather than the unadjusted unit price. Returned discount and tax values are also snapshotted. When the final outstanding quantity on a line is returned, the return absorbs any prior rounding residue so cumulative returns cannot exceed the original line total.

### Boundaries

- Tax percentages are organization-configured product settings; no automatic KRA tax category mapping, VAT exemptions, withholding tax, eTIMS device certification, invoice numbering compliance or statutory filing is asserted.
- Discounts are controlled by the existing `manage` permission, not a configurable threshold/approval matrix. Per-cashier discount limits and manager override PINs remain future work.
- POS refunds remain accounting records only; no M-Pesa/card/bank/cash payout is executed.
- The tax/discount calculation is tax-exclusive and rounds monetary line amounts to two decimal places. Confirm applicable product tax treatment with the organization's tax adviser before production use.


### Product tax administration

- Inventory product creation accepts a configured `tax_rate` percentage.
- `PATCH /api/v1/inventory/products/{product_id}/tax-rate` updates a product's rate and writes an audit event; manage permission is required.
- The Inventory workspace provides the manager-only tax-rate update form.
- New POS transactions snapshot the rate. Existing sale lines and receipts are immutable when the product configuration changes.


## Automatic POS-to-accounting journals

Posted POS sales and approved POS returns now create their corresponding general-ledger journal automatically in the same database transaction as the source POS record whenever the organization has configured its POS ledger mapping. This prevents a source sale/return from committing while its generated journal is only half-written.

Configure tenant-owned active accounts through `PUT /api/v1/accounting/pos-mapping` (manager permission):
- Cash tender → cash asset account
- Card tender → card clearing asset account
- Bank tender → bank clearing asset account
- Credit tender → receivables asset account
- Net sales → sales revenue
- Discounts → sales discounts (contra-revenue)
- Output tax → output tax liability
- Refunds → sales returns (contra-revenue), with tax reversed separately

A sale journal debits each tender/receivable account and discounts, then credits net sales and output tax. A return journal debits sales returns and reverses the tax liability, then credits the relevant refund tender/clearing accounts. Monetary amounts are rounded to two decimal places and each journal is checked for exact debit/credit equality before posting.

- `GET /api/v1/accounting/pos-mapping`
- `PUT /api/v1/accounting/pos-mapping`
- `GET /api/v1/accounting/pos-integrations?status=pending|posted`
- `POST /api/v1/accounting/pos-integrations/post-pending`

Every source has one unique organization/source-type/source-ID bridge link. Replays do not create duplicate journals. When mappings are not configured, or a source date falls in a closed fiscal period, the POS transaction remains operationally recorded and its bridge link stays pending with a reason. After correcting the mapping or period issue, an authorized manager can post pending integrations. The backfill endpoint discovers legacy sales/returns that predate the bridge and processes them in bounded batches. The integration list is branch-scoped.

The mapping uses the organization's chart of accounts and base currency. POS currency must therefore be consistent with the accounting base currency; foreign-currency conversion, payment-gateway settlement, card/M-Pesa execution and bank reconciliation are not performed by this bridge. Finance must verify account classification and statutory tax treatment before production use.
