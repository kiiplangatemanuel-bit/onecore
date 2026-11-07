# Procurement suppliers, purchase orders and goods receipt

This is the first procurement vertical slice. It connects supplier records and
purchase-order approval to the inventory stock ledger.

## Capabilities

- Tenant-owned supplier directory.
- Purchase orders with supplier, branch, currency, notes and product lines.
- Purchase order quantities and unit costs use decimal precision.
- Draft purchase orders require organization-manage permission for approval.
- Goods receipt is only allowed for approved or partially received orders.
- Receipts cannot exceed outstanding order quantities.
- Receipt movements are written into the inventory append-only stock ledger.
- Organization-scoped idempotency keys prevent replay from adding stock twice.
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
- `POST /api/v1/procurement/orders/{id}/receive`

A purchase order is draft on creation. Only a user with organization manage
permission can approve it. Receiving requires an approved or partially received PO.
Each receipt line references a purchase-order line, a positive quantity and a unique
idempotency key. A matching replay is a no-op; reusing the key for different
movement content returns conflict. Successful receipt writes inventory movements
and advances the order to partially_received or received.

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
- GRN document/inspection, rejected/returned goods, supplier invoices and three-way
  matching. Requisition-to-PO conversion is also not yet implemented.
- Tax/freight/discount allocations, landed cost and accounts-payable integration.
- Advanced procurement reporting, audit views, CSV import/export and notifications.
- PostgreSQL concurrent receipt tests, end-to-end branch isolation, security review,
  accessibility and UAT.
