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

## Remaining gaps

- Supplier edit/archive, supplier terms, RFQ/quotation comparison and supplier
  performance reporting are now implemented by this increment.
- Delegated approval, approval expiry/escalation, configurable approver groups and
  branch-specific approval matrices remain future work.
- PO edit/cancel, PDF/email dispatch, supplier acknowledgement and delivery schedule.
- Automated AP journal posting/payment settlement, tax compliance validation,
  credit-note accounting allocation and supplier statement reconciliation remain future work.
- Tax/freight/discount allocations, landed cost and accounts-payable integration.
- Supplier portal/email dispatch, RFQ notification delivery, CSV import/export,
  detailed on-time delivery analytics and procurement dashboard exports.
- PostgreSQL concurrent receipt tests, end-to-end branch isolation, security review,
  accessibility and UAT.


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
