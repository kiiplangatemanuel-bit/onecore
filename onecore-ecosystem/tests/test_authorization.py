from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch

def member(role="staff", scope="*"):
    return SimpleNamespace(role=role, branch_scope=scope)

def test_role_permissions_are_least_privilege():
    require_permission(member("staff"), "read")
    require_permission(member("staff"), "create")
    with pytest.raises(HTTPException) as exc:
        require_permission(member("staff"), "delete")
    assert exc.value.status_code == 403

def test_unknown_role_has_no_permissions():
    with pytest.raises(HTTPException):
        require_permission(member("unexpected"), "read")

def test_wildcard_branch_scope():
    m = member("org_admin", "*")
    assert branch_scope_ids(m) is None
    assert can_access_branch(m, "branch-a")
    assert can_access_branch(m, None)

def test_limited_branch_scope():
    m = member("staff", "branch-a, branch-b")
    assert branch_scope_ids(m) == ["branch-a", "branch-b"]
    assert can_access_branch(m, "branch-a")
    assert not can_access_branch(m, "branch-c")
    assert not can_access_branch(m, None)

def test_empty_branch_scope_denies_all_branches():
    m = member("staff", "")
    assert branch_scope_ids(m) == []
    assert not can_access_branch(m, "branch-a")
