from app.main import app
from app.api.payroll_completion import router as payroll_completion_router


def test_kenya_payroll_routes_are_registered():
    paths = {route.path for route in payroll_completion_router.routes if hasattr(route, "path")}
    assert "/api/v1/hr/payroll/statutory-rules/seed-kenya-2026" in paths
    assert "/api/v1/hr/payroll/runs/{run_id}/calculate-kenya" in paths
    assert "/api/v1/hr/payroll/runs/{run_id}/approve-calculation" in paths
    assert "/api/v1/hr/payroll/runs/{run_id}/post-journal" in paths
    assert "/api/v1/hr/payroll/payment-batches/{batch_id}/bank-reconcile" in paths
    assert "/api/v1/hr/payroll/payment-batches/{batch_id}/post-settlement-journal" in paths
    assert "/api/v1/hr/payroll/my-history" in paths
    assert any(getattr(route, "path", None) == "/health" for route in app.routes)



def test_generic_record_endpoints_cannot_mutate_payroll_records():
    import pytest
    from fastapi import HTTPException
    from app.api.routes import create_record, update_record, delete_record

    with pytest.raises(HTTPException) as create_error:
        create_record("hr-payroll", None, None, None, None)
    assert create_error.value.status_code == 403

    with pytest.raises(HTTPException) as update_error:
        update_record("hr-payroll", 1, None, None, None, None)
    assert update_error.value.status_code == 403

    with pytest.raises(HTTPException) as delete_error:
        delete_record("hr-payroll", 1, None, None, None)
    assert delete_error.value.status_code == 403
