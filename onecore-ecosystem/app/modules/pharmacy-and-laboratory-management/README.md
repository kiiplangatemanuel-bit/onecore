# Pharmacy and Laboratory Management

Master specification category: **9**

## Source scope
Medicine catalogue/classification, prescriptions/dispensing, batches/expiry, stock,
suppliers, pricing and billing; lab catalogue, sample registration/tracking,
processing, result validation, reports, doctor access, equipment, inventory and
quality control.

## Current implementation status
Partial foundation implemented on branch `feature/pharmacy-lab-workflows`:

- Tenant-owned medicine catalogue entries linked to the shared inventory product
  ledger.
- Batch receipt with expiry dates, batch numbers, branch assignment, cost/selling
  price, idempotent retries and append-only stock receipt movements.
- Batch listing with expired/active/quarantined state and quarantine workflow.
- Tenant-owned laboratory test catalogue with specimen type, unit, reference
  range snapshot and turnaround target.
- Laboratory orders tied to a signed clinical encounter and the assigned provider.
- Single-specimen sample accession/collection tracking per order.
- Result entry followed by independent second-person validation; result values and
  reference-range snapshots are retained on the order lines.
- Responsive `/pharmacy-lab` workspace, migration `0026_pharmacy_lab`, tests and
  `docs/PHARMACY_LAB.md`.

## Still required before production
- Prescription creation and pharmacist dispensing with FEFO batch allocation,
  quantity controls, controlled-medicine rules and returns.
- Supplier procurement, purchase invoices, pharmacy pricing/insurance billing,
  patient payment integration and dispensing receipts.
- Multiple specimen containers per order, sample rejection/recollection,
  processing stations, equipment/instrument integration, QC/calibration and
  result correction/amendment workflows.
- Result PDF/portal/clinician delivery, alerts, critical-value escalation and
  clinical review/interpretation policies.
- More granular pharmacy/laboratory role separation, clinical data protection,
  audit/retention governance, concurrency/security tests and UAT.
