from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.models import (
    PharmacyMedicine, PharmacyBatch, LaboratoryTest, LaboratoryOrder,
    LaboratoryOrderLine, LaboratorySample, PharmacyPrescription, PharmacyPrescriptionLine, PharmacyDispense, PharmacyAllergy, PharmacyDrugSafetyRule, PharmacyControlledEvent, PharmacyLabWorkflowRecord, LaboratoryTestPanel, LaboratoryTestPanelLine,
)
from app.core.schemas import (
    PharmacyMedicineIn, PharmacyBatchIn, PharmacyBatchQuarantineIn,
    LaboratoryTestIn, LaboratoryOrderIn, LaboratorySampleIn, LaboratoryResultIn, PharmacyPrescriptionIn, PharmacyDispenseIn, PharmacyAllergyIn, PharmacySafetyRuleIn, PharmacyStockAdjustmentIn, LaboratoryPanelIn, LaboratoryInstrumentResultIn,
)
from app.services.pharmacy_lab import pharmacy_batch_hash, laboratory_order_hash
from app.main import app


def test_pharmacy_medicine_contract_rejects_blank_names():
    medicine = PharmacyMedicineIn(
        sku="MED-001", generic_name="Paracetamol", brand_name="",
        strength="500mg", dosage_form="tablet", route="oral", unit="tablet",
        sale_price="5.00",
    )
    assert medicine.generic_name == "Paracetamol"
    with pytest.raises(ValidationError):
        PharmacyMedicineIn(sku="MED-002", generic_name="  ", dosage_form="tablet")


def test_pharmacy_batch_contract_and_idempotency_hash():
    payload = PharmacyBatchIn(
        client_batch_id="batch-client-0001", batch_number="lot-001",
        branch_id="branch-hq", expiry_date=date.today() + timedelta(days=365),
        received_quantity="100.000", unit_cost="1.20", selling_price="2.00",
    )
    assert payload.received_quantity == Decimal("100.000")
    assert pharmacy_batch_hash(payload, 12) == pharmacy_batch_hash(payload, 12)
    assert pharmacy_batch_hash(payload, 12) != pharmacy_batch_hash(payload, 13)
    with pytest.raises(ValidationError):
        PharmacyBatchIn(
            client_batch_id="batch-client-0002", batch_number="   ",
            branch_id="branch-hq", expiry_date=date.today() + timedelta(days=365),
            received_quantity="1", unit_cost="1", selling_price="2",
        )
    with pytest.raises(ValidationError):
        PharmacyBatchQuarantineIn(reason="   ")


def test_laboratory_test_and_order_contracts():
    test = LaboratoryTestIn(
        code="CBC", name="Complete blood count", specimen_type="EDTA blood",
        unit="cells/uL", reference_range="local range", turnaround_hours=4,
    )
    assert test.specimen_type == "EDTA blood"
    order = LaboratoryOrderIn(client_order_id="lab-order-0001", encounter_id=3, test_ids=[1, 2])
    assert order.test_ids == [1, 2]
    with pytest.raises(ValidationError):
        LaboratoryOrderIn(client_order_id="lab-order-0002", encounter_id=3, test_ids=[1, 1])
    with pytest.raises(ValidationError):
        LaboratoryOrderIn(client_order_id="lab-order-0003", encounter_id=3, test_ids=[0])
    with pytest.raises(ValidationError):
        LaboratoryTestIn(code=" ", name="CBC", specimen_type="Blood")


def test_laboratory_sample_and_result_contracts():
    sample = LaboratorySampleIn(accession_number="ACC-0001", specimen_type="blood")
    assert sample.accession_number == "ACC-0001"
    result = LaboratoryResultIn(result_value="  5.2 mmol/L  ")
    assert result.result_value == "5.2 mmol/L"
    with pytest.raises(ValidationError):
        LaboratoryResultIn(result_value="   ")


def test_laboratory_order_hash_is_independent_of_test_order():
    first = LaboratoryOrderIn(client_order_id="lab-order-0004", encounter_id=3, test_ids=[4, 2, 9])
    second = LaboratoryOrderIn(client_order_id="lab-order-0004", encounter_id=3, test_ids=[9, 4, 2])
    assert laboratory_order_hash(first) == laboratory_order_hash(second)


def test_pharmacy_and_lab_models_and_api_routes_are_registered():
    assert PharmacyMedicine.__tablename__ == "pharmacy_medicines"
    assert PharmacyBatch.__tablename__ == "pharmacy_batches"
    assert LaboratoryTest.__tablename__ == "laboratory_tests"
    assert LaboratoryOrder.__tablename__ == "laboratory_orders"
    assert LaboratoryOrderLine.__tablename__ == "laboratory_order_lines"
    assert LaboratorySample.__tablename__ == "laboratory_samples"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/pharmacy/medicines" in paths
    assert "/api/v1/pharmacy/medicines/{medicine_id}/batches" in paths
    assert "/api/v1/pharmacy/batches" in paths
    assert "/api/v1/pharmacy/batches/{batch_id}/quarantine" in paths
    assert "/api/v1/lab/tests" in paths
    assert "/api/v1/lab/orders" in paths
    assert "/api/v1/lab/orders/{order_id}/sample" in paths
    assert "/api/v1/lab/orders/{order_id}/lines/{line_id}/result" in paths
    assert "/api/v1/lab/orders/{order_id}/validate" in paths
    assert "/pharmacy-lab" in paths


def test_pharmacy_lab_workspace_has_core_workflow_controls():
    from pathlib import Path
    page = Path(__file__).resolve().parents[1] / "app" / "web" / "pharmacy_lab.html"
    html = page.read_text(encoding="utf-8")
    assert 'id="medicine"' in html
    assert 'id="batch"' in html
    assert 'id="labTest"' in html
    assert 'id="labOrder"' in html
    assert 'id="labSample"' in html
    assert 'id="labResult"' in html


def test_pharmacy_and_laboratory_operations_models_are_registered():
    expected = {
        "pharmacy_prescriptions", "pharmacy_prescription_lines", "pharmacy_dispenses",
        "pharmacy_allergies", "pharmacy_drug_safety_rules", "pharmacy_controlled_events",
        "pharmacy_lab_workflow_records", "laboratory_test_panels", "laboratory_test_panel_lines",
    }
    assert expected.issubset(PharmacyPrescription.metadata.tables.keys())
    assert PharmacyPrescription.__tablename__ == "pharmacy_prescriptions"
    assert PharmacyDispense.__tablename__ == "pharmacy_dispenses"
    assert PharmacyLabWorkflowRecord.__tablename__ == "pharmacy_lab_workflow_records"


def test_prescription_dispensing_and_safety_schema_validation():
    rx = PharmacyPrescriptionIn(
        encounter_id=10, prescription_number="RX-2026-001",
        valid_until=date.today()+timedelta(days=10),
        lines=[{"medicine_id":2,"dose":"1 tablet","frequency":"twice daily",
                "duration_days":5,"quantity":"10","refills_allowed":1}],
    )
    assert rx.lines[0].quantity == Decimal("10")
    dispense = PharmacyDispenseIn(line_id=1,batch_id=2,quantity=Decimal("2"),
        idempotency_key="dispense-unique-001",verifier_id=9)
    assert dispense.quantity == Decimal("2")
    with pytest.raises(ValidationError):
        PharmacyDispenseIn(line_id=1,batch_id=2,quantity=Decimal("0"),
            idempotency_key="dispense-unique-001",verifier_id=9)
    with pytest.raises(ValidationError):
        PharmacySafetyRuleIn(medicine_a_id=1,rule_type="interaction",
            severity="block",description="Requires two medicine IDs")


def test_lab_panel_and_analyzer_contracts():
    panel = LaboratoryPanelIn(code="CBC-PANEL",name="Full blood count",test_ids=[1,2])
    assert panel.test_ids == [1,2]
    result = LaboratoryInstrumentResultIn(accession_number="ACC-100",
        test_code="CBC",result_value="4.5",is_critical=True)
    assert result.is_critical is True
    with pytest.raises(ValidationError):
        PharmacyStockAdjustmentIn(quantity_delta=0,reason="No adjustment",verifier_id=3)


def test_pharmacy_lab_advanced_routes_are_registered():
    paths=set(app.openapi()["paths"])
    expected={
        "/api/v1/pharmacy/prescriptions","/api/v1/pharmacy/prescriptions/{prescription_id}/dispense",
        "/api/v1/pharmacy/allergies","/api/v1/pharmacy/safety-rules",
        "/api/v1/pharmacy/dispenses/{dispense_id}/return",
        "/api/v1/pharmacy/dispenses/{dispense_id}/reverse",
        "/api/v1/pharmacy/batches/{batch_id}/recall",
        "/api/v1/pharmacy/batches/{batch_id}/adjust",
        "/api/v1/pharmacy/replenishment","/api/v1/pharmacy-lab/billing",
        "/api/v1/pharmacy-lab/claims/{claim_id}/decision",
        "/api/v1/lab/panels","/api/v1/lab/samples/{sample_id}/decision",
        "/api/v1/lab/instruments","/api/v1/lab/instruments/{instrument_id}/results",
        "/api/v1/lab/instruments/{instrument_id}/qc",
        "/api/v1/lab/instruments/{instrument_id}/calibration",
        "/api/v1/lab/critical-alerts","/api/v1/lab/orders/{order_id}/deliver",
        "/api/v1/lab/public-deliveries/{delivery_id}","/api/v1/pharmacy-lab/traceability",
    }
    assert expected.issubset(paths)
