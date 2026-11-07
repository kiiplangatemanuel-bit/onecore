# Inventory catalogue and stock ledger

This increment delivers the first inventory vertical slice on the OneCore shared
platform. It is not a complete warehouse management, procurement or POS product.

## Capabilities

- Organization-scoped product catalogue with SKU uniqueness per tenant.
- Append-only quantity movement ledger using decimal precision (3 decimal places).
- Receipt, issue and adjustment movement types with direction validation.
- Stock balances derived from ledger movements; no independently mutable balance
  counter is exposed.
- Branch ownership validation and branch-scope enforcement for reads and postings.
- Per-organization idempotency keys to make client retries safe against duplicate
  movement creation.
- Audit events for product creation and stock movement posting.
- Accessible browser interface at `/inventory`; API paths are under
  `/api/v1/inventory`.

## API

- `GET /api/v1/inventory/products`
- `POST /api/v1/inventory/products`
- `GET /api/v1/inventory/stock?product_id={id}&branch_id={id}`
- `POST /api/v1/inventory/movements`

All API operations require a valid bearer token and active organization membership
using `X-Organization-ID` on the shared host (or the verified tenant host). Read
operations require the membership read permission; product and movement creation
require create permission. Branch-scoped users must post movements against an
authorized branch.

A receipt uses a positive `quantity_delta`; an issue uses a negative value; an
adjustment accepts either sign but cannot result in negative stock. Every movement
requires a client-generated unique `idempotency_key`. Replaying the same key and
same movement returns the original movement; reusing it for different content
returns HTTP 409.

Example movement:

```json
{
  "product_id": 42,
  "branch_id": "branch-uuid",
  "quantity_delta": "12.500",
  "movement_type": "receipt",
  "reference": "GRN-2026-001",
  "idempotency_key": "grn-2026-001-line-1"
}
```

## Migration and operations

Migration `0002_inventory` creates the inventory product and stock movement
tables, tenant indexes and idempotency uniqueness constraint. Apply it with
`alembic upgrade head` from `onecore-ecosystem`. CI tests upgrade and downgrade
of the migration chain.

## Explicitly not delivered in this slice

- Supplier records, purchase requisitions, purchase orders, approval matrices,
  goods-received notes, supplier invoices and three-way matching.
- Multi-warehouse transfers, reservations, batch/lot/serial tracking, expiry,
  reorder rules, costing methods (FIFO/weighted average), valuation and stocktake
  reconciliation.
- POS checkout, payment capture/refunds, tax invoices, cash drawer/shift control,
  offline transaction queue, conflict resolution and device synchronization.
- Inventory frontend edit/deactivate/search/filter/pagination and richer reporting.
- End-to-end API tests for concurrent idempotency and branch isolation under
  PostgreSQL load.

Do not use this inventory ledger as a substitute for financial accounting or
provider-certified tax/payment workflows.
## Inventory completion workflows (migration 0033)

The extended inventory API adds:

- Tenant/branch-scoped warehouses and transfer orders with dispatch, tracking references, in-transit state and receipt confirmation. Source stock is deducted at dispatch and destination stock is added only on receipt; idempotent movement keys prevent duplicate ledger postings.
- Sales-order and POS-order stock reservations with expiry timestamps, idempotency keys, release and an expiry sweep endpoint. Active unexpired reservations reduce available-to-promise quantities.
- Lot/batch/serial receipt, expiry metadata, FEFO/FIFO batch issuing, and damaged/expired/quarantined disposition with audit events.
- Stocktakes with captured expected and counted quantities, maker-checker approval and append-only variance adjustments.
- Per-warehouse reorder thresholds, lead-time-aware suggested quantities, simple moving-average demand forecasts, multi-store dashboard and inventory alerts.
- Organization and branch-specific price lists with per-product prices and promotion percentages.
- Batch-layer inventory valuation using recorded receipt costs, with FIFO and weighted-average reporting modes.

### API entry points

- `GET/POST /api/v1/inventory/warehouses`
- `POST /api/v1/inventory/transfers`, `POST /api/v1/inventory/transfers/{id}/dispatch`, `POST /api/v1/inventory/transfers/{id}/receive`
- `POST /api/v1/inventory/reservations`, `POST /api/v1/inventory/reservations/{id}/release`, `POST /api/v1/inventory/reservations/expire`
- `POST /api/v1/inventory/batches/receive`, `POST /api/v1/inventory/batches/issue`, `PATCH /api/v1/inventory/batches/{id}/status`
- `POST /api/v1/inventory/stocktakes`, `POST /api/v1/inventory/stocktakes/{id}/approve`
- `PUT /api/v1/inventory/reorder-rules`, `GET /api/v1/inventory/replenishment`, `GET /api/v1/inventory/forecast`
- `GET /api/v1/inventory/valuation`, `GET /api/v1/inventory/dashboard`, `GET /api/v1/inventory/alerts`
- `POST /api/v1/inventory/price-lists`, `PUT /api/v1/inventory/price-lists/{id}/prices`

### Operational constraints still requiring deployment/UAT

- Reservations expire when the expiry sweep is run; schedule that endpoint through the deployment's trusted job runner for automatic periodic expiry.
- Replenishment returns suggested purchase quantities; procurement order creation and supplier fulfillment remain separate approval-controlled procurement actions.
- The demand forecast is a transparent simple moving average, not a trained predictive model; tune its window and seasonality against real business data.
- Legacy branch-level movements without a warehouse are attributed to the sole active warehouse at that branch. Where a branch has multiple warehouses, opening stock must be assigned through controlled warehouse opening-balance movements before warehouse-level availability is reliable.
- Provider/carrier GPS tracking is not included; transfer tracking references are entered by staff.
- Validate costing policy, tax treatment, serial/lot regulatory requirements, concurrency and performance with PostgreSQL production-like data before go-live.
