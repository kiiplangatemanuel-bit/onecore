from pathlib import Path


def test_react_procurement_workspace_is_mounted_and_api_backed():
    root = Path(__file__).resolve().parents[2]
    component = (root / "frontend" / "src" / "ProcurementWorkspace.jsx").read_text(encoding="utf-8")
    app = (root / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    for endpoint in (
        "/api/v1/procurement/suppliers",
        "/api/v1/inventory/products",
        "/api/v1/branches",
        "/api/v1/procurement/orders",
        "/api/v1/procurement/requisitions",
        "/api/v1/procurement/goods-receipts",
        "/api/v1/procurement/supplier-settlements",
        "/api/v1/procurement/accounting-reconciliation",
    ):
        assert endpoint in component
    assert 'path==="/procurement"?<ProcurementWorkspace' in app
    assert "SUPABASE_DB_URL" in component
    assert "Select supplier" in component
    assert "Select product" in component
    assert '["id","ID"]' in component
    assert "getToken" in component
    legacy = (root / "onecore-ecosystem" / "app" / "web" / "procurement.html").read_text(encoding="utf-8")
    assert "onecore_access_token" in legacy
    assert "history.replaceState" in legacy
