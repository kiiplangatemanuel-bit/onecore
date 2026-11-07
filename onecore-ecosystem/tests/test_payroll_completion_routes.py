from app.main import app
from app.api.payroll_completion import router as payroll_completion_router


def test_kenya_payroll_routes_are_registered():
    paths = {route.path for route in payroll_completion_router.routes if hasattr(route, "path")}
    assert "/hr/payroll/statutory-rules/seed-kenya-2026" in paths
    assert "/hr/payroll/runs/{run_id}/calculate-kenya" in paths
    assert "/hr/payroll/runs/{run_id}/approve-calculation" in paths
    assert "/hr/payroll/runs/{run_id}/post-journal" in paths
    assert "/hr/payroll/payment-batches/{batch_id}/bank-reconcile" in paths
    assert "/hr/payroll/my-history" in paths
    assert any(getattr(route, "path", None) == "/health" for route in app.routes)
