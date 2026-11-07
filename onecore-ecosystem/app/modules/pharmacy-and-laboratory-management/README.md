# Pharmacy and Laboratory Management

Master specification category: **9**

## Implementation status

Core pharmacy and laboratory workflows are implemented in the shared healthcare encrypted-resource boundary and are exposed at `/pharmacy-lab` and `/api/v1`. See [PHARMACY_LAB_OPERATIONS.md](../../../docs/PHARMACY_LAB_OPERATIONS.md) for workflow/API details and external release gates.

### Pharmacy delivered
- Medicine catalogue and inventory product mapping; branch batch receipt, expiry, FEFO dispensing, quarantine, recalls and verified stock adjustments.
- Clinician- and encounter-validated e-prescriptions, pharmacist dispensing with independent verification, partial fills, refill limits and cancellation.
- Patient allergy and configured drug-interaction checks at prescription and dispense time.
- Controlled-medicine event audit, traceable returns, independent return disposition, restocking and dispense reversal.
- Supplier replenishment requests converted to procurement purchase orders.
- Pharmacy billing and shared healthcare insurance claim settlement reconciliation.

### Laboratory delivered
- Configurable test catalogue, reference and critical ranges, specimen types, prices and single-specimen test panels.
- Clinician encounter-linked orders, multi-sample accessioning, sample acceptance/rejection and custody handoff/receipt chain.
- Result entry, automatic numeric critical-range alert queue and independent validation.
- Analyzer registration, one-time API keys, rotation/revocation, QC, calibration and authenticated analyzer result ingestion.
- Secure clinician result delivery and one-time expiring patient result access.
- Laboratory billing, insurer claim workflow and end-to-end audit traceability.

### Validation and production boundaries

Automated route/contract tests are included. Do not call this production-certified until the current PR-head CI passes and the clinical/pharmacy/lab UAT and external integrations listed in `docs/PHARMACY_LAB_OPERATIONS.md` are accepted. The configured interaction catalogue is not a licensed drug knowledge base; analyzer ingestion is a credentialed contract, not a vendor-certified HL7/ASTM adapter; critical alerts are queued in-app and require a live notification adapter for SMS/pager escalation.
