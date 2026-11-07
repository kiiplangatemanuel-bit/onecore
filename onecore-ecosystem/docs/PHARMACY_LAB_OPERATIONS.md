# Pharmacy and Laboratory Operations

The domain API is registered in the OneCore application under `/api/v1`. The interactive workspace is served at `/pharmacy-lab`. Patient-linked payloads use the healthcare encrypted-resource boundary, patient access grants, branch authorization and healthcare audit events. Stock changes are posted to the shared append-only inventory stock movement ledger.

## Pharmacy workflows

- Tenant-wide medicine catalogue linked to inventory products, including generic/brand name, active ingredient, strength, dosage form, route, unit, price and controlled-medicine classification.
- Branch-level batches with batch number, expiry, received quantity, cost and selling price; batch receipts create inventory ledger movements.
- FEFO dispensing from locked, unexpired batches; insufficient stock, expired batches and recalled/quarantined stock are excluded.
- Electronic prescriptions are created only by the clinician assigned to an open patient encounter. Prescription lines capture dose, frequency, duration, quantity, refill allowance and validity.
- Allergy and configured interaction rules are checked at prescription time and rechecked at dispensing against the patient's active prescriptions. Severe/blocking rules prevent the operation; warnings are returned for pharmacist review.
- Pharmacist dispensing requires a distinct second pharmacist/healthcare-admin verifier. Partial fills and refill requests are recorded against the authorized prescription quantity.
- Prescriptions can be cancelled by the prescriber or healthcare administrator, retaining the dispensed history.
- Dispense returns are traced to their original batch allocations. Returned stock remains out of saleable inventory until a second pharmacist verifies sealed product for restocking; quarantine and discard are separately recorded.
- Dispense reversals require independent verification, restore prescription balances, reverse the linked invoice and post only the approved quantity back to eligible batches.
- Batch quarantine, recall, expiry sweep and stock adjustment are audited. Stock adjustments require a second verifier and idempotency key.
- Replenishment requests can be converted into draft procurement purchase orders for active tenant suppliers.
- Controlled medicine receipts, dispenses, adjustments, returns and reversals create append-only controlled-medicine audit events.

## Laboratory workflows

- Configurable test catalogue with specimen type, unit, reference range, critical low/high thresholds, price and turnaround target; tests can be updated or deactivated while historical order snapshots remain intact.
- Configurable panels; panel tests are restricted to a single specimen type because each order has a specimen-specific collection workflow.
- Lab orders require an open encounter assigned to the ordering clinician and snapshot test catalogue data at order time. Accepted specimens move through an explicit processing state before result verification.
- Multiple sample/accession records per order, specimen collection, barcode/accession, acceptance/rejection, handoff/receipt custody events and chain-of-custody history.
- Result entry requires an accepted sample. Numeric critical thresholds automatically queue critical alerts; authorized users can additionally flag a result critical.
- Independent result validation prevents the result author from validating their own work.
- Analyzer instruments have one-time API credentials, rotation and revocation. Analyzer result ingestion is authenticated by the instrument key and is blocked unless the latest QC passed and calibration remains in date.
- QC records have an explicit validity date; analyzer ingestion is blocked when QC has expired or failed. Calibration due dates are enforced. QC, calibration, critical-alert acknowledgement, secure clinician delivery and one-time expiring patient result links are audited.
- Laboratory orders can be invoiced only after result validation. Pharmacy dispense invoices use the actual batch selling prices. Insurance claims can be submitted, approved/rejected and settled through the shared healthcare claim settlement route so invoice balances are reconciled.

## API and workspace

The workspace is a signed-in API workbench for the pharmacy and laboratory routes. API paths and request payloads are documented by FastAPI OpenAPI at `/docs`. Common endpoints include:

- `POST /api/v1/pharmacy/prescriptions`, `/dispense`, `/refill`, `/cancel`
- `POST /api/v1/pharmacy/dispenses/{id}/return` and `/pharmacy/returns/{id}/disposition`
- `POST /api/v1/lab/orders`, `/start-processing`, `/samples`, `/results`, `/validate`; `PUT /api/v1/lab/tests/{id}` and `POST /api/v1/lab/tests/{id}/deactivate`
- `POST /api/v1/lab/instruments/{id}/results` using `X-Instrument-Key` and a unique analyzer `result_id`
- `POST /api/v1/pharmacy-lab/billing`, `/claims/{id}/decision`, `/claims/{id}/settle`; `GET /api/v1/pharmacy/reports/stock` and `GET /api/v1/lab/reports/operations`

## Production release gates and external dependencies

The implementation supplies configurable drug interaction rules; it does not bundle a licensed, clinically maintained drug-interaction database. Clinical governance must approve and maintain the allergy/interaction catalogue, dosing rules, formulary and controlled-drug policy.

The analyzer endpoint is a credentialed integration contract, not a tested vendor-specific HL7/ASTM/POCT adapter. Each equipment manufacturer adapter, mapping, connectivity, sandbox and site acceptance test must be completed. Critical alerts are durably queued and acknowledged in the application; real-time SMS/pager/voice escalation requires a monitored notification adapter and on-call schedule.

Insurer claim records and settlement reconciliation are internal workflows; live insurer eligibility, e-claims gateways and payment movement require payer/bank credentials and UAT. Pharmacy supplier replenishment creates draft procurement orders; purchase approval and receipt remain in procurement workflows.

Before live clinical use, complete pharmacy/lab user acceptance testing, clinical governance sign-off, Kenya Pharmacy and Poisons Board/SASRA-independent applicable regulatory review, data-protection assessment, security/penetration testing, PostgreSQL concurrency/load testing, encryption key custody/rotation, backup/restore drills and external device/payer integration tests. This code is not a clinical safety certification or regulatory approval.
