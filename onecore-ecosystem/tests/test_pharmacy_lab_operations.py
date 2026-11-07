from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.pharmacy_lab import _critical_result, _decimal
from app.core.models import HealthcareResource, HealthcareEvent
from app.main import app


def test_pharmacy_and_laboratory_routes_are_registered():
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/pharmacy/medicines",
        "/api/v1/pharmacy/medicines/{medicine_id}/batches",
        "/api/v1/pharmacy/batches",
        "/api/v1/pharmacy/batches/{batch_id}/quarantine",
        "/api/v1/pharmacy/batches/{batch_id}/recall",
        "/api/v1/pharmacy/batches/expire",
        "/api/v1/pharmacy/batches/{batch_id}/adjust",
        "/api/v1/pharmacy/prescriptions",
        "/api/v1/pharmacy/prescriptions/{prescription_id}/dispense",
        "/api/v1/pharmacy/prescriptions/{prescription_id}/refill",
        "/api/v1/pharmacy/prescriptions/{prescription_id}/cancel",
        "/api/v1/pharmacy/dispenses/{dispense_id}/return",
        "/api/v1/pharmacy/returns/{return_id}/disposition",
        "/api/v1/pharmacy/dispenses/{dispense_id}/reverse",
        "/api/v1/pharmacy/replenishment",
        "/api/v1/lab/tests",
        "/api/v1/lab/panels",
        "/api/v1/lab/orders",
        "/api/v1/lab/orders/{order_id}/samples",
        "/api/v1/lab/samples/{sample_id}/custody",
        "/api/v1/lab/samples/{sample_id}/decision",
        "/api/v1/lab/orders/{order_id}/results",
        "/api/v1/lab/orders/{order_id}/validate",
        "/api/v1/lab/instruments",
        "/api/v1/lab/instruments/{instrument_id}/rotate-key",
        "/api/v1/lab/instruments/{instrument_id}/revoke",
        "/api/v1/lab/instruments/{instrument_id}/qc",
        "/api/v1/lab/instruments/{instrument_id}/calibration",
        "/api/v1/lab/instruments/{instrument_id}/results",
        "/api/v1/lab/critical-alerts",
        "/api/v1/lab/orders/{order_id}/deliver",
        "/api/v1/lab/public-deliveries/{delivery_id}",
        "/api/v1/pharmacy-lab/billing",
        "/api/v1/pharmacy-lab/claims/{claim_id}/decision",
        "/api/v1/pharmacy-lab/claims/{claim_id}/settle",
        "/api/v1/pharmacy-lab/traceability",
    }
    assert expected.issubset(paths)
    assert HealthcareResource.__tablename__ == "healthcare_resources"
    assert HealthcareEvent.__tablename__ == "healthcare_events"


def test_decimal_validation_rejects_invalid_precision_and_non_finite_values():
    assert _decimal("12.345", "quantity", positive=True) == Decimal("12.345")
    with pytest.raises(HTTPException):
        _decimal("0", "quantity", positive=True)
    with pytest.raises(HTTPException):
        _decimal("1.2345", "quantity", places=3)
    with pytest.raises(HTTPException):
        _decimal("NaN", "quantity")


def test_lab_critical_result_thresholds():
    line = {"critical_low": "2.0", "critical_high": "10.0"}
    assert _critical_result(line, "1.9")
    assert _critical_result(line, "10.0")
    assert not _critical_result(line, "5.0")
    assert not _critical_result(line, "not numeric")
    assert _critical_result({}, "normal", requested=True)
