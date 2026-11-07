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
  performance.
- Configurable multi-level approval limits, delegated approval, monetary thresholds,
  and segregation-of-duties policies beyond the manager gate.
- PO edit/cancel, PDF/email dispatch, supplier acknowledgement and delivery schedule.
- Supplier invoices and three-way matching; rejected stock is recorded but supplier
  return/credit-note processing is not yet implemented. Requisition-to-PO conversion is also not yet implemented.
- Tax/freight/discount allocations, landed cost and accounts-payable integration.
- Advanced procurement reporting, audit views, CSV import/export and notifications.
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
