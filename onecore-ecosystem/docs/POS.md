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
cash/card/bank tender records are manual; M-Pesa STK Push is available through
the configured Safaricom Daraja integration and is settled only after verified callback.

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
- Cash/card/bank refund rows remain operational records; M-Pesa refunds can be sent
  through the Daraja B2C flow and are marked paid only after a successful result callback.
- Return valuation uses the original tax-inclusive discounted line snapshots.
  POS returns create a pending accounting bridge until every allocated payout is confirmed.

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
- Card/bank gateway integrations and automated settlement feeds remain future work.
  M-Pesa requires approved Daraja credentials, a public HTTPS callback host and
  production shortcode/B2C entitlements; sandbox CI does not prove live provider settlement.
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
- M-Pesa B2C payout is supported for eligible refunds; cash/card/bank payout execution
  remains manual. A B2C timeout is treated as an uncertain outcome and must be reconciled
  with Safaricom before retrying to avoid duplicate disbursement.
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


## Safaricom M-Pesa Daraja collections and refunds

The POS accepts an `mpesa` tender allocation as **unsettled**. After the POS sale is
synchronized, an authorized manager initiates an STK Push using
`POST /api/v1/integrations/mpesa/pos/sales/{sale_id}/payments/{payment_id}/stk-push`
with a Kenyan phone number. The customer must approve the prompt on their handset.
The initiation response is not proof of payment. Only a matching Daraja STK callback
with a successful result, matching CheckoutRequestID, exact amount and a receipt
number changes the tender to recorded and retries the pending POS journal.

Payment status is available at
`GET /api/v1/integrations/mpesa/pos/sales/{sale_id}/payments`.
Duplicate callbacks are idempotent. Callback URLs contain high-entropy one-time tokens;
only token hashes are stored. Callback handlers do not require a logged-in user.

For refunds, the return flow can record an `mpesa` refund allocation as pending.
A manager initiates its B2C disbursement through
`POST /api/v1/integrations/mpesa/pos/returns/{return_id}/refunds/{refund_id}/b2c`.
The refund is marked recorded only after a successful B2C result callback with a
transaction receipt. Timeouts and failed results do not claim that money was sent.
B2C requires an approved Daraja shortcode, initiator name, pre-encrypted security
credential, and registered result and timeout callback URLs. A B2C intent in
`initiating`, `pending`, `success`, `unknown`, `timeout` or `exception`
cannot be submitted again automatically. In particular, transport failures and
timeouts are ambiguous provider outcomes; reconcile the transaction with Safaricom
before any manual retry. Only a definitive provider rejection/failure is eligible
for a new attempt.

A callback may arrive before the initiation HTTP response is saved. The one-time
callback token can bind that first callback to its provider checkout/conversation ID,
and the later initiation response is checked against the callback-bound ID instead
of overwriting a completed result. This preserves successful collections/refunds
even when the provider response races the callback or the client connection drops.

M-Pesa receipt references are unique within an organization for payment tenders and
refund allocations. A receipt already allocated elsewhere is quarantined as an
exception and cannot settle a second transaction. A B2C request whose provider
correlation IDs are missing is retained as unknown and cannot be retried automatically.

A successful STK callback must include the exact checkout request ID, payer phone,
whole-KES amount and a receipt. A successful B2C callback must include the expected
conversation ID, exact transaction amount and a receipt. Missing or mismatched
provider fields put the intent into `exception` and leave the POS tender/refund
unsettled. Provider receipts are checked against previously applied receipts to
prevent duplicate settlement. The Daraja API base URL must be HTTPS on a
Safaricom-owned host. The POS creates M-Pesa tenders as unsettled; the sales journal
does not debit the M-Pesa clearing account until the successful STK callback.
Likewise, the return journal does not credit the M-Pesa clearing account until the
successful B2C result callback.

### Required environment configuration

- `INTEGRATION_MPESA_ENABLED=true`
- `MPESA_BASE_URL=https://sandbox.safaricom.co.ke` (or approved production Daraja host)
- `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`
- `MPESA_SHORTCODE`, `MPESA_PASSKEY`, and `MPESA_TRANSACTION_TYPE` (`CustomerPayBillOnline` or `CustomerBuyGoodsOnline`)
- `MPESA_CALLBACK_URL=https://your-public-host/api/v1/integrations/mpesa/callbacks`
- For B2C: `MPESA_INITIATOR_NAME`, `MPESA_SECURITY_CREDENTIAL` (Safaricom-encrypted),
  `MPESA_B2C_RESULT_URL`, and `MPESA_B2C_TIMEOUT_URL`.

STK and B2C Daraja amounts are whole KES shillings. Fractional-shilling tenders or
refunds are rejected for provider execution and must be handled by another tender
or a separately approved reconciliation process. The organization's POS accounting
mapping currently posts confirmed M-Pesa collections/refunds to the configured bank
clearing account; configure that account as the M-Pesa clearing control account.
Safaricom sandbox credentials and registered callback URLs are required for live
end-to-end verification. Production activation also requires a Safaricom-approved
shortcode and B2C permissions; these cannot be provisioned by repository code.


## POS shift reconciliation and cash management

Opening float is recorded when a cashier opens a shift. Cash-in, cash-out and safe-drop operations are append-only, tenant-idempotent records. Cash-out and safe drops require manager permission. The cash ledger is available at GET /api/v1/pos/shifts/{shift_id}/reconciliation and movements are created at POST /api/v1/pos/shifts/{shift_id}/cash-movements.

Expected till cash = opening float + recorded cash sales - recorded cash refunds + cash-in - cash-out - safe drops. Unsettled tenders and unconfirmed refunds are excluded. Shift close supports KES denomination counts (1, 5, 10, 20, 40, 50, 100, 200, 500 and 1,000) and validates their sum against the declared count. Non-zero variances are sent to manager review with approve/reject and mandatory notes; zero-variance shifts auto-reconcile. All actions are tenant/branch scoped and audit logged.


## Shift reconciliation and till cash management

Every cashier shift has a branch-scoped cash ledger. The expected till balance is
calculated from the opening float, recorded cash tenders, confirmed cash refunds,
cash-in movements, and cash-out/safe-drop movements. Unsettled M-Pesa and credit
tenders are excluded until they are recorded as collected cash.

- `GET /api/v1/pos/shifts/{shift_id}/reconciliation` returns the expected balance,
  component totals, denomination count, variance, review status and movement history.
- `POST /api/v1/pos/shifts/{shift_id}/cash-movements` records cash-in, cash-out or
  safe-drop entries. Cash-out and safe-drop require manager permission. An
  organization-scoped idempotency key prevents duplicate movement recording, and
  reusing a key with different movement details is rejected.
- Cash-out and safe-drop amounts cannot exceed the calculated available till balance.
- `POST /api/v1/pos/shifts/{shift_id}/close` requires a physical KES denomination
  breakdown; the sum must equal the declared closing cash. It snapshots expected
  cash and variance and closes the shift.
- A zero-variance shift is automatically reconciled. A non-zero variance is marked
  `pending_review`; a manager must approve or reject it with a mandatory note using
  `POST /api/v1/pos/shifts/{shift_id}/review`.
- Cash movement records are append-only operational records and produce audit
  events. Shifts and movements are tenant/branch scoped; cashiers can manage their
  own open shifts, while managers can review shifts and authorize outflows.
- The POS screen includes cash movement entry, live reconciliation, denomination
  counting, shift close and variance review controls.

This is a single-cashier shift control workflow. It does not yet provide physical
cash drawer hardware integration, multi-cashier shared tills, bank deposit
reconciliation or production till-count pilot sign-off.


## Advanced POS controls (migration 0035)

The advanced POS API adds organization-scoped device enrollment, supervisor approval and revocation:
- `POST /api/v1/pos/advanced/devices/register` issues a high-entropy device secret once and creates a pending device.
- `GET /api/v1/pos/advanced/devices`, `POST /devices/{id}/decision` and `POST /devices/{id}/revoke` provide supervisor device lifecycle controls.
- `POST /devices/{id}/session` verifies the stored device secret against a trusted device. Cashier authentication remains a separate user session; this endpoint is not a substitute for the normal bearer token.

Offline conflict cases can be recorded with client/server snapshots and resolved by a manager:
- `POST /conflicts`, `GET /conflicts`, `POST /conflicts/{id}/resolve`.
- The server deliberately rejects direct acceptance of an unvalidated client payload. The safe resolution is to accept server state, void the local transaction, or refresh and retry through ordinary server-side validation.

Client sync telemetry is append-only and idempotent:
- `POST /sync-events` records queued, attempting, synced, retrying, dead-letter and conflict events.
- `GET /sync-dashboard` provides branch-scoped counts and recent failures.
- This is an operational telemetry API; a deployed client/background worker must submit events. It does not create a server-side worker or guarantee a browser Background Sync event will run on every platform.

Customer membership and loyalty:
- `POST /customers` creates/updates organization-scoped customer membership records.
- `GET /customers`, `GET /customers/{id}/history`, `POST /customers/{id}/loyalty/award` and `POST /customers/{id}/loyalty/redeem`.
- Checkout accepts an optional `customer_ref` on the POS sync payload and stores a tenant-scoped customer foreign key on the sale. Customer history returns linked posted sales and loyalty ledger entries; it never infers a customer from a phone-number match.
- Loyalty awards and redemptions use organization-scoped idempotency keys and row locks. Awards are supervisor-controlled; automatic earning rules and redemption-as-checkout-discount remain a separate pricing-policy integration.

Multi-store reporting:
- `GET /operations-report` aggregates posted sale counts, gross totals and distinct shifts by branch within the caller's branch scope.

Hardware and live payment boundaries:
- Cash drawer and thermal printer execution remain browser/OS/driver integration points; the API does not claim to operate a particular USB, Bluetooth or serial device without an installed supported driver and physical device acceptance test.
- M-Pesa Daraja collection/refund callbacks remain the verified provider settlement path documented above. Card/bank settlement feeds and automated reconciliation require provider credentials and integrations.
- Device trust metadata is not hardware attestation. Production offline operation still requires managed endpoint encryption, secure key storage, device policy, and a validated offline entitlement/session renewal design.
