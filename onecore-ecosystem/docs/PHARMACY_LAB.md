# OneCore Pharmacy and Laboratory workflows

This increment adds the initial medicine stock and laboratory workflow foundation.
It does not yet implement full prescription dispensing or laboratory instrument
automation.

## Pharmacy

- `POST /api/v1/pharmacy/medicines` creates a medicine catalogue entry and its
  linked shared inventory product.
- `GET /api/v1/pharmacy/medicines` lists active medicines.
- `POST /api/v1/pharmacy/medicines/{medicine_id}/batches` receives a branch-owned
  batch. It rejects expired stock, stores batch/expiry/cost/selling price and writes
  a positive append-only inventory receipt movement in the same transaction.
- `GET /api/v1/pharmacy/batches` lists batches by medicine, branch and state.
  Expired batches are identified from their expiry date; quarantined stock is
  separately visible.
- `POST /api/v1/pharmacy/batches/{batch_id}/quarantine` quarantines an active
  batch with a recorded reason.
- Batch receipt has tenant-unique client IDs and canonical request hashes to make
  identical retries idempotent and conflicting reuse return HTTP 409.

No prescription, dispensing, stock issue, FEFO allocation, controlled medicine
approval, supplier invoice, insurance billing or patient payment workflow is
included yet. Received batches remain unissued in the stock ledger until a later
dispensing increment is implemented.

## Laboratory

- `POST /api/v1/lab/tests` and `GET /api/v1/lab/tests` manage the tenant test
  catalogue with specimen type, unit, reference range and turnaround target.
- `POST /api/v1/lab/orders` creates a laboratory order for a signed encounter.
  Only the encounter's assigned provider may order tests. A single order must use
  one specimen type; tests requiring different specimen types are separated.
- `GET /api/v1/lab/orders` and `GET /api/v1/lab/orders/{order_id}` list and
  retrieve orders, sample accession and result details.
- `POST /api/v1/lab/orders/{order_id}/sample` registers one collected sample per
  order with a tenant-unique accession number.
- `POST /api/v1/lab/orders/{order_id}/lines/{line_id}/result` records a result
  after collection. Unit and reference range are snapshotted from the test
  catalogue when the order is created.
- `POST /api/v1/lab/orders/{order_id}/validate` requires a different user from
  every result author. It validates all result lines together and locks the order.

Results are operator-entered text; no automated interpretation, clinical diagnosis
or instrument feed is performed. There is no result amendment after validation,
multi-container specimen handling, quality-control/calibration workflow or
patient/clinician result delivery.

## Controls and production boundaries

All routes require active tenant membership and the current `manage` permission
for writes/clinical order/result workflows. Pharmacy and lab records are
organization-scoped and branch-checked. Read and mutation events are audited.
Pharmacy batch receipts use the shared inventory stock ledger. Lab orders are
linked to signed healthcare encounters.

This slice does not add field-level encryption, granular pharmacist/lab-technician
roles, patient consent/portal, record retention/deletion governance, critical-value
escalation, medical-device integration, regulator-specific controls or production
UAT. Clinical result text and patient links are stored in the application database.
Do not use live patient results or controlled medicine operations until privacy,
clinical governance, pharmacy policy, security and operational controls have been
reviewed and approved.
