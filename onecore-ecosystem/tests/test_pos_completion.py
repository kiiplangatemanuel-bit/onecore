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
