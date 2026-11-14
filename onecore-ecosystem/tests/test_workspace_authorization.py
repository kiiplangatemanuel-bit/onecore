from types import SimpleNamespace

from app.core.authorization import (
    branch_scope_ids,
    can_access_branch,
    has_module_permission,
    require_module_permission,
)
from app.api.workspace import _entitled_modules
from app.core.tenancy import _module_for_path, _module_entitlements, _action_for_request


def member(role="org_admin", scope="*"):
    return SimpleNamespace(role=role, branch_scope=scope)


def test_module_access_requires_role_and_module_grant():
    assert has_module_permission(member("org_admin"), "accounting", "read")
    assert has_module_permission(member("accountant"), "accounting", "read")
    assert not has_module_permission(member("accountant"), "inventory", "read")
    assert not has_module_permission(member("viewer"), "accounting", "create")
    assert not has_module_permission(member("unknown_role"), "accounting", "read")


def test_module_permission_denies_unknown_module_and_action():
    assert not has_module_permission(member("org_admin"), "unknown_module", "execute")
    try:
        require_module_permission(member("viewer"), "accounting", "create")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("Expected module permission denial")


def test_branch_scope_is_explicit_and_closed_by_default():
    assert branch_scope_ids(member("org_admin", "*")) is None
    assert branch_scope_ids(member("staff", "branch-a,branch-b")) == ["branch-a", "branch-b"]
    assert branch_scope_ids(member("staff", "")) == []
    assert can_access_branch(member("staff", "branch-a"), "branch-a")
    assert not can_access_branch(member("staff", "branch-a"), "branch-b")
    assert not can_access_branch(member("staff", ""), "branch-a")


def test_entitlement_parser_supports_list_and_boolean_map_only():
    assert _entitled_modules({"modules": ["accounting", "inventory"]}) == {"accounting", "inventory"}
    assert _entitled_modules({"modules": {"accounting": True, "inventory": False}}) == {"accounting"}
    assert _entitled_modules({}) == set()
    assert _entitled_modules({"modules": "all"}) == set()



def test_api_namespace_resolves_to_single_module_entitlement_keys():
    assert _module_for_path("/api/v1/accounting/journals") == "accounting"
    assert _module_for_path("/api/v1/inventory/products") == "inventory"
    assert _module_for_path("/api/v1/healthcare/patients") == "hospital"
    assert _module_for_path("/api/v1/sacco/members") == "sacco"
    assert _module_for_path("/api/v1/pharmacy/medicines") == "pharmacy"
    assert _module_for_path("/api/v1/lab/tests") == "laboratory"
    assert _module_for_path("/api/v1/records/accounting") == "accounting"
    assert _module_for_path("/api/v1/workspace/context") is None


def test_effective_module_entitlement_parser_is_fail_closed():
    assert _module_entitlements({"modules": ["accounting", "reports"]}) == {"accounting", "reports"}
    assert _module_entitlements({"modules": {"accounting": True, "pos": False}}) == {"accounting"}
    assert _module_entitlements({"modules": "all"}) == set()
    assert _module_entitlements({}) == set()



def request(method, path):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path))


def test_business_api_routes_resolve_school_hr_and_payroll_entitlements():
    assert _module_for_path("/api/v1/school/fees/payments") == "school"
    assert _module_for_path("/api/v1/hr/employees") == "hr"
    assert _module_for_path("/api/v1/payroll/statutory-batches") == "payroll"
    assert _module_for_path("/api/v1/integrations/mpesa/payments") == "accounting"


def test_http_methods_and_workflow_actions_resolve_to_rbac_actions():
    assert _action_for_request(request("GET", "/api/v1/accounting/journals")) == "read"
    assert _action_for_request(request("POST", "/api/v1/accounting/journals")) == "create"
    assert _action_for_request(request("PATCH", "/api/v1/accounting/journals/1")) == "update"
    assert _action_for_request(request("POST", "/api/v1/payroll/runs/1/approve")) == "update"
    assert _action_for_request(request("POST", "/api/v1/sacco/withdrawals/1/decision")) == "update"
    assert _action_for_request(request("DELETE", "/api/v1/inventory/products/1")) == "delete"


def test_approver_roles_get_only_their_narrow_workflow_update_rights():
    assert has_module_permission(member("payroll_approver"), "payroll", "update")
    assert not has_module_permission(member("payroll_approver"), "payroll", "create")
    assert has_module_permission(member("hr_manager"), "hr", "update")
    assert not has_module_permission(member("hr_manager"), "payroll", "create")
