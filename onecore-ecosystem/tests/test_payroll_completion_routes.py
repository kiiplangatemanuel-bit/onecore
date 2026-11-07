from app.main import app


def test_kenya_payroll_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/api/v1/hr/payroll/statutory-rules/seed-kenya-2026" in paths
    assert "/api/v1/hr/payroll/runs/{run_id}/calculate-kenya" in paths
    assert "/api/v1/hr/payroll/runs/{run_id}/approve-calculation" in paths
    assert "/api/v1/hr/payroll/runs/{run_id}/post-journal" in paths
    assert "/api/v1/hr/payroll/payment-batches/{batch_id}/bank-reconcile" in paths
    assert "/api/v1/hr/payroll/my-history" in paths
