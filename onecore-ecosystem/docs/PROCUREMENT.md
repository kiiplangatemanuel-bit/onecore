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

## Remaining gaps

- Supplier edit/archive, supplier terms, RFQ/quotation comparison and supplier
  performance.
- Purchase requisitions, configurable multi-level approval limits and segregation
  of duties beyond the organization-manage gate.
- PO edit/cancel, PDF/email dispatch, supplier acknowledgement and delivery schedule.
- GRN document/inspection, rejected/returned goods, supplier invoices and three-way
  matching.
- Tax/freight/discount allocations, landed cost and accounts-payable integration.
- Procurement UI, reporting, audit views, CSV import/export and notifications.
- PostgreSQL concurrent receipt tests, end-to-end branch isolation, security review,
  accessibility and UAT.
