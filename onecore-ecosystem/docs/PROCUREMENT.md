# Procurement suppliers, purchase orders and goods receipt

This is the first procurement vertical slice. It connects supplier records and
purchase-order approval to the inventory stock ledger.

## Capabilities

- Tenant-owned supplier directory.
- Purchase orders with supplier, branch, currency, notes and product lines.
- Purchase order quantities and unit costs use decimal precision.
- Draft purchase orders require organization-manage permission for approval.
- Goods receipt is only allowed for approved or partially received orders.
- GRNs are recorded as pending inspection; delivered quantities reserve the PO balance.
- Inspection must account for every delivered unit as accepted or rejected.
- Rejected quantities require a reason; only accepted quantities enter the inventory stock ledger.
- GRN receipt keys and accepted-stock movement keys are idempotent.
- Branch scope checks and audit events.
- API under `/api/v1/procurement`.

## API

- `GET/POST /api/v1/procurement/requisitions`
- `GET /api/v1/procurement/requisitions/{id}`
- `POST /api/v1/procurement/requisitions/{id}/submit`
- `POST /api/v1/procurement/requisitions/{id}/approve`
- `POST /api/v1/procurement/requisitions/{id}/reject`

- `GET/POST /api/v1/procurement/suppliers`
- `GET/POST /api/v1/procurement/orders`
- `POST /api/v1/procurement/orders/{id}/approve`
- `POST /api/v1/procurement/orders/{id}/cancel` (manager/admin only; requires a reason; draft/approved orders with no GRN or supplier invoice only)
- `POST /api/v1/procurement/orders/{id}/goods-receipts`
- `GET /api/v1/procurement/goods-receipts`
- `GET /api/v1/procurement/goods-receipts/{id}`
- `POST /api/v1/procurement/goods-receipts/{id}/inspect`
- Legacy direct-to-stock `POST /api/v1/procurement/orders/{id}/receive` returns HTTP 410

A purchase order is draft on creation. Only a user with organization manage
permission can approve it. Receiving requires an approved or partially received PO.
Each GRN line references a purchase-order line, a positive delivered quantity and a unique
idempotency key. The GRN remains pending inspection and does not increase stock. An
authorized manager must account for each delivered unit as accepted or rejected;
rejected units require a reason of at least five characters. Only accepted units create
inventory receipt movements, using a stable GRN-line movement key. Inspection is a
single atomic action; successful completion marks the GRN inspected. The PO's received
quantity tracks delivered quantities, not accepted stock.

## Requisition workflow increment — 7 November 2026

A requisition can be created as a draft with a branch, justification and one or more
unique product lines. The requester submits it for review. Only a manager with
organization-manage permission can approve or reject a submitted request, and the
requester cannot review their own request. Rejection requires a reason. All reads and
writes are organization- and branch-scoped, status transitions are locked while being
changed, and create/submit/approve/reject actions are audited. This is a separate
request-control workflow; approval does not automatically create a purchase order.

Migration `0014_procurement_requisitions` creates requisition headers and lines and
supports downgrade. The procurement workspace provides draft creation, submission,
and manager review actions. Automated tests cover schema constraints, duplicate
product prevention, model registration and API route registration. CI must pass
migration upgrade/downgrade/re-upgrade, compilation and the complete test suite before
this increment is considered verified.

## Controlled purchase-order cancellation

Managers and organization administrators can cancel a draft or approved PO using
 `POST /api/v1/procurement/orders/{id}/cancel` with a JSON `reason` of at least five
 characters. The operation locks the PO row, enforces tenant and branch scope, and
 refuses cancellation once any goods receipt (including pending inspection) or supplier
 invoice exists. It does not delete lines, reverse stock, alter AP, or erase approval
 history; it changes the PO status to `cancelled` and records an audit event. Orders with
 downstream activity must be resolved through their receipt, return, invoice and AP
 workflows rather than being silently rolled back. Supplier notification/acknowledgement
 is not implied by this internal status change.

## Remaining implementation and production gates

The current mainline includes the requisition, PO approval, RFQ/quotation, supplier invoice matching, returns, AP integration, supplier settlement/remittance, supplier statement reconciliation, delegated approval, supplier portal and discrepancy/reconciliation workflows described below. Do not use the earlier "Remaining gaps" bullets as a current statement that those delivered features are absent.

Still not evidenced as complete in the current repository:
- PO amendments, supplier acknowledgement and scheduled delivery milestones. Controlled cancellation is now available only before any GRN or supplier invoice exists; downstream reversals remain deliberately blocked pending explicit accounting and stock reversal workflows.
- Complete tax/freight/discount/landed-cost allocation across receipt and AP accounting.
- Automated supplier email/RFQ/remittance notifications and reliable delivery tracking beyond supplier-reported updates.
- Full CSV bulk import/export and detailed on-time delivery analytics/dashboard exports.
- Direct bank-provider payment initiation; bank statement import/matching exists separately.
- PostgreSQL concurrency/locking tests for receipts, invoice allocation and settlements; end-to-end branch-isolation tests, accessibility audit and production UAT.

These are distinct implementation slices and must not be represented as completed merely because the advanced workflow APIs exist.



## GRN inspection increment — 7 November 2026

Migration `0015_procurement_grn_inspection` adds GRN headers and lines. A GRN is created
against an approved/partially received PO and moves to `pending_inspection`. PO line
received quantities are reserved at delivery to prevent over-receipt. An organization-
and branch-scoped manager inspects the entire GRN in one operation. Accepted plus
rejected must equal delivered quantity for every line; rejected quantity requires a
reason. Accepted stock alone is posted to the inventory movement ledger, and its
idempotency key is derived from the immutable GRN line ID. Re-inspection is rejected.
The former direct receive endpoint is deprecated and returns HTTP 410 so new receipts
cannot bypass inspection. The workspace includes GRN creation and inspection forms.

Tests cover payload validation, unique receipt line/key constraints, model and route
registration, legacy endpoint deprecation and workspace controls. CI migration and test
results are the verification gate for this increment.


## Procurement completion increment — 7 November 2026

### Requisition conversion

`POST /api/v1/procurement/requisitions/{id}/convert-to-order` converts an approved
requisition into a draft PO using its original branch, products and requested quantities.
The caller selects the supplier, currency and unit costs. A requisition is guarded
against duplicate conversion; PO approval remains a separate control.

### RFQ and quotation comparison

`POST /api/v1/procurement/rfqs` creates an RFQ, its product/quantity lines and supplier
invitations. Invited suppliers can submit one complete quotation per RFQ. Comparison
returns line pricing, tax, delivery days and total by currency. Awarding a complete
quotation creates a draft PO and closes the RFQ; the PO must still pass its approval
workflow. Currency totals are deliberately not compared across different currencies.

### Approval policy

`PUT /api/v1/procurement/approval-rules` replaces the organization's sequential PO
approval tiers. Rules define amount ranges, level and required role. The PO approval
endpoint records one distinct approver per level, prevents the PO creator from approving,
and only releases the order after all applicable levels have approved. Approval
history is available from `/procurement/orders/{id}/approvals`. Manager/admin roles
are checked at each approval step.

### Supplier invoice matching

`POST /api/v1/procurement/supplier-invoices` validates supplier and PO identity, exact
PO unit prices, and invoice quantities against accepted, non-returned and not-yet-
invoiced inspected GRN quantities. Duplicate supplier invoice numbers are rejected by
a database unique index. Successfully matched invoice records are retained with their
line details and totals. This endpoint does not yet post an AP journal or settle payment.

### Supplier returns and performance

`POST /api/v1/procurement/goods-receipts/{id}/returns` returns previously accepted
quantities only, rejects duplicate/excess returns and insufficient stock, and writes
negative stock ledger movements with unique idempotency keys. The return records the
supplier's credit-note reference. `/procurement/supplier-performance` reports PO/GRN
counts, delivered/accepted quantities and acceptance rate.

### Database, UI and tests

Migration `0016_procurement_completion` adds approval tiers/actions, RFQs/invitations/
quotes, supplier invoices and supplier returns. The procurement workspace now exposes
forms for conversion, RFQs, quotation comparison/award, approval policy, invoice
matching, supplier returns and performance reporting. Automated tests cover payload
constraints, model/table registration, OpenAPI route registration and workspace
controls. CI must pass migration upgrade, downgrade/re-upgrade, compilation and pytest.


## Procurement settlement and supplier governance increment

Branch: `feature/procurement-settlement-governance`; migration `0033_procurement_workflows`.

### Supplier settlement and remittance
- `POST /api/v1/procurement/supplier-settlements` creates an idempotent settlement instruction with one or more allocations to posted AP invoices for the same supplier, currency and branch.
- Allocations are locked and checked against each AP invoice's remaining balance. The payment account must be an active asset account and settlement currency must equal the organization's base currency.
- Manual/bank-transfer instructions remain pending verification until an authorized manager confirms the external reference. M-Pesa supplier payouts use Safaricom Daraja B2C, configured initiator/security credential and HTTPS result/timeout callbacks.
- Daraja initiation is persisted before the network call. Callback tokens are high-entropy and only their SHA-256 hashes are stored. Supplier payouts use the same configured B2C result/timeout URL base as the existing POS refund integration; the shared `/api/v1/integrations/mpesa/callbacks/b2c/result/{token}` and timeout handlers dispatch to POS refund or supplier settlement intents. Callback processing checks conversation/originator correlation, exact amount, receipt presence and duplicate receipts, with a partial unique database index for M-Pesa supplier receipts. Successful callbacks set `provider_confirmed`; a separate authorized manager verification posts the AP/cash journal and invoice-payment allocations.
- Unknown/timeout B2C outcomes are not automatically retried; reconcile with Safaricom before any new payout instruction.
- `GET /supplier-settlements/{id}/remittance` returns a remittance advice with the invoice allocation breakdown and posted journal reference.

### Credit notes and supplier statement reconciliation
- `POST /supplier-returns/{return_id}/post-credit-note` converts returned accepted quantities into a posted supplier AP credit note against the AP invoice linked to the matched procurement bill.
- It allocates quantities to the original AP invoice lines, subtracts previously posted credit-note quantities, reverses the expense/asset and input-tax accounts, debits AP, and posts a balanced journal in an open fiscal period.
- Supplier statements can be imported, matched line-by-line to original gross AP invoices, AP payments, posted supplier credit notes or consolidated supplier settlement remittances, then reconciled only when every line is matched and opening balance plus statement movements equals closing balance.

### Delegated approvals and supplier portal
- Delegations are tenant-scoped, time-bounded, branch-aware, auditable and reject overlapping active windows for the same principal. A delegate can approve only the next applicable purchase-order approval tier for the delegated principal's role; the creator cannot approve their own order. Managers can escalate a pending tier to a higher-authority approver through a time-limited substitution.
- Supplier portal tokens are random, stored as SHA-256 digests, scoped to one supplier, expiring and revocable. The portal supports invited RFQs, quote submission, purchase-order details, supplier invoices and delivery updates. Tokens are shown only once at creation.

### Discrepancy and reconciliation controls
- Invoice discrepancies can be opened against matched/accounted source invoices and resolved with an auditable resolution note after the invoice returns to a matched/accounted state. An evidence-based auto-resolution action rechecks purchase-order prices, accepted/returned receipt quantities, source/AP totals and duplicate references; unresolved discrepancies remain open for manual correction.
- `GET /accounting-reconciliation` compares procurement source invoice gross values to AP net values after posted supplier credits, checks each settlement allocation against its AP payment record, verifies AP-control debits and cash/bank credits in the posted journal, and requires the cash journal line to be matched to an imported bank statement line.

### API routes added
- `POST /supplier-invoices/{id}/integrate-to-ap`
- `POST/GET /supplier-settlements`
- `POST /supplier-settlements/{id}/verify`
- `GET /supplier-settlements/{id}/remittance`
- `POST /supplier-settlements/callbacks/b2c/result/{token}`
- `POST /supplier-settlements/callbacks/b2c/timeout/{token}`
- `POST/GET /approval-delegations`, `POST /approval-delegations/{id}/revoke`
- `POST /orders/{id}/approve-as-delegate`
- `POST /supplier-portal/tokens`, `POST /supplier-portal/tokens/{id}/revoke`
- `GET /supplier-portal/rfqs`, `POST /supplier-portal/rfqs/{id}/quotes`
- `GET /supplier-portal/purchase-orders`, `GET /supplier-portal/purchase-orders/{id}`
- `GET /supplier-portal/invoices`, `POST /supplier-portal/delivery-updates`
- `POST /supplier-statements`, `GET /supplier-statements/{id}`
- `POST /supplier-statements/{id}/lines/{line_id}/match`, `POST /supplier-statements/{id}/reconcile`
- `POST /supplier-returns/{id}/post-credit-note`
- `POST /supplier-invoices/{id}/discrepancies`, `POST /invoice-discrepancies/{id}/resolve`
- `GET /accounting-reconciliation`

### Production boundaries and release gates
- Migration `0033_procurement_workflows` adds durable settlement/allocation, delegation, portal-token, discrepancy and supplier-statement records. Alembic registers the new mapped models.
- The M-Pesa path requires production Daraja B2C entitlement, Safaricom-approved initiator and encrypted credential, public HTTPS callbacks, production secrets and provider UAT. Sandbox checks do not prove production disbursement.
- Bank-transfer settlement is recorded and manager-verified; there is no direct bank API initiation in this increment. Bank reconciliation uses the existing accounting statement matching workflow.
- Supplier delivery updates are supplier-reported events, not GPS/carrier tracking. Email delivery of remittance advice and automated supplier notifications require configured outbound messaging and are not claimed here.
- Invoice discrepancy records support auditable exception resolution; they do not silently rewrite supplier invoices or override price/quantity/tax controls.
- Run migration upgrade, downgrade/re-upgrade, Python compilation, the full pytest suite, PostgreSQL concurrency tests and end-to-end provider/bank UAT before merge/deployment. Do not regard the branch as verified until its latest CI checks pass.
