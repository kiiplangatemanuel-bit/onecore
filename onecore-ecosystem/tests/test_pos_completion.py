from app.main import app
from app.core.pos_completion_models import POSDevice, POSOfflineConflict, POSCustomer, POSLoyaltyEntry, POSPeripheralCommand, POSCustomerSale

def test_pos_completion_models_registered():
    assert POSDevice.__tablename__ == "pos_devices"
    from app.core.models import POSShift
    assert "device_id" in POSShift.__table__.columns
    assert POSOfflineConflict.__tablename__ == "pos_offline_conflicts"
    assert POSCustomer.__tablename__ == "pos_customers"
    assert POSLoyaltyEntry.__tablename__ == "pos_loyalty_entries"
    assert POSPeripheralCommand.__tablename__ == "pos_peripheral_commands"
    assert POSCustomerSale.__tablename__ == "pos_customer_sales"

def test_pos_completion_routes_registered():
    paths=set(app.openapi()["paths"])
    expected={
        "/api/v1/pos/devices/register",
        "/api/v1/pos/devices/{device_id}/approve",
        "/api/v1/pos/devices/{device_id}/bind-shift",
        "/api/v1/pos/devices/{device_id}/revoke",
        "/api/v1/pos/devices/{device_id}/conflicts",
        "/api/v1/pos/conflicts",
        "/api/v1/pos/conflicts/{conflict_id}/resolve",
        "/api/v1/pos/sync/monitor",
        "/api/v1/pos/customers",
        "/api/v1/pos/customers/{customer_id}/history",
        "/api/v1/pos/customers/{customer_id}/rewards/redeem",
        "/api/v1/pos/peripherals/commands",
        "/api/v1/pos/devices/{device_id}/peripherals/commands",
        "/api/v1/pos/payments/{payment_id}/verify-settlement",
        "/api/v1/pos/refunds/{refund_id}/confirm-execution",
        "/api/v1/pos/operations/report",
    }
    assert expected <= paths

def test_pos_device_credentials_are_not_stored_as_plaintext():
    import inspect
    from app.api.pos_completion import _hash
    token="test-device-secret-token"
    assert _hash(token) != token
    assert len(_hash(token)) == 64

def test_pos_device_headers_are_allowed_by_cors():
    from app.main import app
    cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    allowed = {header.lower() for header in cors.kwargs["allow_headers"]}
    assert "x-organization-id" in allowed
    assert "x-pos-device-token" in allowed


def test_pos_service_worker_uses_safe_background_sync():
    from pathlib import Path
    worker = (Path(__file__).parents[1] / "app" / "web" / "pos-sw.js").read_text(encoding="utf-8")
    assert 'event.tag === "onecore-pos-sync"' in worker
    assert '"/api/v1/pos/sync"' in worker
    assert 'response.status === 409' in worker
    assert "Preserve FIFO order until a supervisor resolves this transaction" in worker
    assert 'payment.method === "mpesa"' in worker

def test_pos_database_guards_prevent_duplicate_open_device_and_customer_phone():
    from app.core.models import POSShift
    from app.core.pos_completion_models import POSCustomer
    shift_indexes = {index.name for index in POSShift.__table__.indexes}
    customer_indexes = {index.name for index in POSCustomer.__table__.indexes}
    assert "uq_pos_shift_open_device" in shift_indexes
    assert "uq_pos_customer_phone" in customer_indexes

def test_pos_workspace_renders_all_operational_dashboards():
    from pathlib import Path
    page = (Path(__file__).parents[1] / "app" / "web" / "pos.html").read_text(encoding="utf-8")
    for element_id in (
        "refreshSyncMonitor", "syncMonitorSummary", "syncMonitorList",
        "refreshConflicts", "conflictSummary", "conflictList",
        "refreshOperationsReport", "operationsSummary", "branchReport", "terminalReport",
    ):
        assert f'id="{element_id}"' in page



def test_pos_loyalty_policy_model_and_routes():
    from app.core.pos_completion_models import POSLoyaltyRewardPolicy

    assert POSLoyaltyRewardPolicy.__tablename__ == "pos_loyalty_reward_policies"
    paths = set(app.openapi()["paths"])
    assert "/api/v1/pos/loyalty/reward-policy" in paths
    assert "get" in app.openapi()["paths"]["/api/v1/pos/loyalty/reward-policy"]
    assert "put" in app.openapi()["paths"]["/api/v1/pos/loyalty/reward-policy"]


def test_pos_loyalty_policy_schema_bounds():
    from app.api.pos_completion import LoyaltyRewardPolicyIn
    from pydantic import ValidationError

    valid = LoyaltyRewardPolicyIn(
        earn_points_per_100_units=1, points_per_currency_unit=100,
        max_redemption_percent="50.00", is_active=True,
    )
    assert valid.points_per_currency_unit == 100
    with pytest.raises(ValidationError):
        LoyaltyRewardPolicyIn(
            earn_points_per_100_units=-1, points_per_currency_unit=100,
            max_redemption_percent="50.00",
        )
    with pytest.raises(ValidationError):
        LoyaltyRewardPolicyIn(
            earn_points_per_100_units=1, points_per_currency_unit=0,
            max_redemption_percent="50.00",
        )
    with pytest.raises(ValidationError):
        LoyaltyRewardPolicyIn(
            earn_points_per_100_units=1, points_per_currency_unit=100,
            max_redemption_percent="100.01",
        )
