from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.tenancy import _enforce_module_entitlement


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter_by(self, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def limit(self, count):
        return self

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, subscriptions=(), plan=None):
        self.subscriptions = list(subscriptions)
        self.plan = plan

    def query(self, model):
        return FakeQuery(self.subscriptions)

    def get(self, model, identity):
        return self.plan


def membership(role="org_admin", organization_id=7):
    return SimpleNamespace(role=role, organization_id=organization_id)


def subscription(status="active", override=None):
    return SimpleNamespace(
        status=status, starts_at=None, ends_at=None, plan_id=3,
        entitlements_override=override,
    )


def test_active_plan_grants_only_entitled_modules():
    plan = SimpleNamespace(entitlements={"modules": ["accounting"]})
    db = FakeDB([subscription()], plan)
    _enforce_module_entitlement(db, membership(), "accounting")
    with pytest.raises(HTTPException) as denied:
        _enforce_module_entitlement(db, membership(), "inventory")
    assert denied.value.status_code == 403


def test_organization_override_replaces_plan_modules():
    plan = SimpleNamespace(entitlements={"modules": ["accounting"]})
    db = FakeDB([subscription(override={"modules": ["inventory"]})], plan)
    _enforce_module_entitlement(db, membership(), "inventory")
    with pytest.raises(HTTPException) as denied:
        _enforce_module_entitlement(db, membership(), "accounting")
    assert denied.value.status_code == 403


def test_suspended_subscription_blocks_business_module_access():
    plan = SimpleNamespace(entitlements={"modules": ["accounting", "inventory"]})
    db = FakeDB([subscription(status="suspended")], plan)
    with pytest.raises(HTTPException) as denied:
        _enforce_module_entitlement(db, membership(), "accounting")
    assert denied.value.status_code == 403


def test_legacy_tenant_without_subscription_retains_transition_access():
    _enforce_module_entitlement(FakeDB(), membership(), "accounting")


def test_role_module_grant_is_required_even_with_plan_entitlement():
    plan = SimpleNamespace(entitlements={"modules": ["accounting", "*"]})
    db = FakeDB([subscription()], plan)
    with pytest.raises(HTTPException) as denied:
        _enforce_module_entitlement(db, membership(role="viewer"), "accounting")
    assert denied.value.status_code == 403
