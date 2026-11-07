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


## Advanced pharmacy and laboratory operations (7 November 2026)

Migration `0027_pharmacy_lab_operations` extends the existing `0026_pharmacy_lab` schema.

### Pharmacy API additions

- Electronic prescriptions are issued only from a signed encounter by its assigned prescriber, with an active organization membership and an authorized prescriber role. Prescription lines snapshot medicine, dose, frequency, duration, authorized quantity and refill allowance.
- Patient allergy records and tenant-configured interaction/allergy rules are checked before issuance. Severe allergy and configured blocking rules reject the prescription; warning rules are returned for clinical review.
- Pharmacist dispensing requires a second active pharmacist/supervisor membership as verifier. It locks the prescription line and batch, checks expiry/status/medicine match and stock, permits partial quantities and authorized refills, consumes stock through the shared append-only inventory ledger and creates a pharmacy invoice work item.
- Controlled medicine receipt, dispensing, return, reversal, quarantine, expiry, recall and stock adjustment create append-only controlled-event evidence. Dispensing and adjustments require a separate verifier.
- Returns are recorded for quarantine and are deliberately not restored to saleable stock. A separate independently verified reversal can restock only an active, unexpired batch and posts a compensating stock receipt.
- Quarantine, expiry sweeps and recalls remove remaining quantities from the shared available inventory ledger so another sales channel cannot issue that stock.
- Replenishment requests can be converted into draft procurement purchase orders with a selected active tenant supplier and the expected unit cost.
- Pharmacy and laboratory invoices and insurer claim work items are tenant-scoped, auditable records with claim decision transitions.

### Laboratory API additions

- Configurable test panels are built from tenant-owned active catalogue tests.
- Samples can be accepted/rejected with reason and chain-of-custody events; rejected orders can receive replacement accession samples. Multiple containers/samples per order are supported.
- Analyzer instruments are registered with a random API key whose hash is stored; the key is returned once and must be supplied in the `X-Instrument-Key` header. Incoming results are matched to an accepted accession and pending test line.
- Analyzer results are blocked until a passing QC record and a passing, in-date calibration record exist for that instrument. A failed latest QC or overdue/failed calibration blocks result ingestion.
- Critical results create an auditable escalation queue. Laboratory results still require independent human verification; analyzer imports do not auto-approve clinical results.
- Validated results can be queued for secure in-app clinician delivery or patient delivery using a one-time token with a seven-day expiry. Patient token delivery is intended for HTTPS-only deployment and must be shared through an approved channel.
- Result delivery access, QC, calibration, instrument imports, sample custody, billing, claims, recalls and stock events are visible in the traceability endpoint.

### Important clinical and operational boundaries

- Drug interaction and allergy checks are a tenant-maintained rules engine, not a licensed drug knowledge base or comprehensive clinical decision support. It does not replace pharmacist/prescriber judgement or external interaction databases. Only configured allergens and rules can be detected.
- Prescriber validation verifies encounter assignment and the configured organization role; it does not verify professional registration against the Pharmacy and Poisons Board or another licensing authority.
- The instrument API is a generic authenticated ingestion contract. Vendor-specific HL7, ASTM, FHIR, proprietary analyzer drivers, device certification and instrument vendor UAT remain required.
- QC and calibration are operator-entered evidence. This code does not itself measure controls or calibrate physical equipment.
- Critical result escalation and result delivery are durable in-app queues; no SMS/email/push delivery provider or patient portal account integration is configured here.
- Insurance claims are workflow records, not live insurer eligibility, preauthorization, adjudication or payment integrations. Invoice records do not collect money.
- Supplier replenishment conversion creates a draft procurement purchase order. Procurement approval, supplier transmission, goods receipt, invoice matching and payment remain in the Procurement workflow.
- Controlled medicine audit events are application-level append-only records; database administrator tamper resistance, statutory controlled-drug registers and regulator reporting still require independent controls.
- Multi-sample order support is enabled. Result lines remain one result per test line; repeat testing and corrected-result amendments require a separate reviewed workflow.
- Production deployment still requires clinical/pharmacy governance, licensed-provider verification, patient privacy review, secure key management, penetration testing, PostgreSQL concurrency/load tests, backup/restore validation and end-to-end hospital UAT. No clinical, pharmaceutical or regulatory certification is claimed.
