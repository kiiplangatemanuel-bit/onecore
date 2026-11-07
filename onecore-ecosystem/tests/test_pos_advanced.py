from app.main import app
from app.api.pos_advanced import (
    POSDevice, POSSyncConflict, POSSyncEvent, POSCustomer, POSLoyaltyEntry,
    DeviceRegisterIn, DeviceSessionIn, ConflictIn, ConflictResolveIn, SyncEventIn,
    LoyaltyAwardIn, LoyaltyRedeemIn, token_hash,
)
from pydantic import ValidationError
import pytest


def test_advanced_pos_models_are_registered():
    assert POSDevice.__tablename__ == "pos_devices"
    assert POSSyncConflict.__tablename__ == "pos_sync_conflicts"
    assert POSSyncEvent.__tablename__ == "pos_sync_events"
    assert POSCustomer.__tablename__ == "pos_customers"
    assert POSLoyaltyEntry.__tablename__ == "pos_loyalty_entries"


def test_advanced_pos_routes_are_mounted():
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/pos/advanced/devices/register",
        "/api/v1/pos/advanced/devices",
        "/api/v1/pos/advanced/devices/{device_id}/decision",
        "/api/v1/pos/advanced/devices/{device_id}/revoke",
        "/api/v1/pos/advanced/devices/{device_id}/session",
        "/api/v1/pos/advanced/conflicts",
        "/api/v1/pos/advanced/conflicts/{conflict_id}/resolve",
        "/api/v1/pos/advanced/sync-events",
        "/api/v1/pos/advanced/sync-dashboard",
        "/api/v1/pos/advanced/customers",
        "/api/v1/pos/advanced/customers/{customer_id}/loyalty/award",
        "/api/v1/pos/advanced/customers/{customer_id}/loyalty/redeem",
        "/api/v1/pos/advanced/customers/{customer_id}/history",
        "/api/v1/pos/advanced/operations-report",
    }
    assert expected <= paths


def test_device_registration_requires_stable_device_identity():
    valid = DeviceRegisterIn(branch_id="branch-001", device_key="a" * 32,
                             name="Front counter", platform="ChromeOS")
    assert valid.device_key == "a" * 32
    with pytest.raises(ValidationError):
        DeviceRegisterIn(branch_id="branch-001", device_key="short", name="Till")


def test_conflict_resolution_does_not_accept_unvalidated_client_payload():
    assert ConflictResolveIn(resolution="retry_after_refresh", note="Refresh server state").resolution == "retry_after_refresh"
    with pytest.raises(ValidationError):
        ConflictResolveIn(resolution="accept-anyway", note="Unsafe")
    with pytest.raises(ValidationError):
        ConflictIn(branch_id="branch-001", client_transaction_id="x",
                   conflict_type="unknown", client_snapshot={}, server_snapshot={})


def test_sync_events_and_loyalty_contracts():
    event = SyncEventIn(branch_id="branch-001", event_id="event-0000001",
                        transaction_id="sale-00001", state="dead_letter", attempt=8,
                        error_code="NETWORK", error_message="Repeated timeout")
    assert event.state == "dead_letter" and event.attempt == 8
    assert LoyaltyAwardIn(sale_id=1, entry_key="award-sale-0001", points=10)
    assert LoyaltyRedeemIn(entry_key="redeem-0001", points=5, note="Use points")
    with pytest.raises(ValidationError):
        LoyaltyRedeemIn(entry_key="redeem-0002", points=0, note="Bad amount")


def test_device_secret_digest_is_one_way_and_deterministic():
    digest = token_hash("high-entropy-device-secret")
    assert digest == token_hash("high-entropy-device-secret")
    assert digest != "high-entropy-device-secret"



def test_device_secret_is_submitted_as_body_not_url_parameter():
    payload = DeviceSessionIn(device_secret="x" * 48)
    assert len(payload.device_secret) == 48
    operation = app.openapi()["paths"]["/api/v1/pos/advanced/devices/{device_id}/session"]["post"]
    assert "requestBody" in operation
    assert all(parameter["name"] != "device_secret" for parameter in operation.get("parameters", []))


def test_customer_ref_is_part_of_offline_sale_idempotency_hash():
    from app.core.schemas import POSSaleSyncIn
    from app.services.pos import canonical_request_hash
    base = dict(client_transaction_id="offline-sale-0001", shift_id=1,
                branch_id="branch-001", lines=[{"product_id":2,"quantity":"1"}],
                payments=[{"method":"cash","amount":"10.00"}])
    first = POSSaleSyncIn(**base, customer_ref="member-001")
    second = POSSaleSyncIn(**base, customer_ref="member-002")
    assert canonical_request_hash(first) != canonical_request_hash(second)
