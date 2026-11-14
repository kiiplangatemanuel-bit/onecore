"""Central tenant-role and branch-scope authorization helpers.

Membership.branch_scope is either "*" (all branches) or a comma-separated
list of branch identifiers. Empty scopes intentionally grant no branch access.
"""
from fastapi import HTTPException

ROLE_PERMISSIONS = {
    "org_admin": {"read", "create", "update", "delete", "manage"},
    "branch_admin": {"read", "create", "update", "delete"},
    "manager": {"read", "create", "update"},
    "accountant": {"read", "create", "update"},
    "staff": {"read", "create"},
    "viewer": {"read"},
    # School role grants are narrow; portal reads also require explicit learner links.
    "teacher": {"read", "create", "update"},
    "guardian": {"read"},
    "school_admin": {"read", "create", "update", "delete", "manage"},
    "hr_admin": {"read"},
    "hr_manager": {"read"},
    "payroll_manager": {"read"},
    "payroll_approver": {"read"},
    "payroll_payment": {"read"},
    "payroll_accounting": {"read"},
    "sacco_officer": {"read", "create", "update"},
    "sacco_manager": {"read", "create", "update", "delete"},
    "sacco_kyc_approver": {"read", "update"},
    "sacco_treasurer": {"read", "create", "update"},
    "sacco_auditor": {"read"},
}

def require_permission(membership, action: str) -> None:
    """Raise 403 unless the membership role explicitly grants action."""
    allowed = ROLE_PERMISSIONS.get((membership.role or "").lower(), set())
    if action not in allowed:
        raise HTTPException(status_code=403, detail="Insufficient organization permissions")

def branch_scope_ids(membership):
    """Return None for unrestricted access, otherwise the allowed branch IDs."""
    raw = (membership.branch_scope or "").strip()
    if raw == "*":
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]

def can_access_branch(membership, branch_id) -> bool:
    allowed = branch_scope_ids(membership)
    if allowed is None:
        return True
    return branch_id is not None and str(branch_id) in allowed


# Module-level grants are deliberately separate from broad CRUD grants. A role
# must have both the requested action and an explicit module grant. Unknown
# roles/modules fail closed.
ROLE_MODULES = {
    "org_admin": {"*"},
    "branch_admin": {"*"},
    "manager": {"dashboard", "accounting", "crm", "inventory", "procurement", "pos",
                "hr", "payroll", "school", "hospital", "pharmacy", "laboratory",
                "sacco", "property", "hotel", "restaurant", "reports", "documents"},
    "accountant": {"dashboard", "accounting", "payroll", "reports", "documents"},
    "staff": {"dashboard", "inventory", "pos", "crm", "documents"},
    "viewer": {"dashboard", "reports", "documents"},
    "teacher": {"dashboard", "school", "documents"},
    "guardian": {"dashboard", "school"},
    "school_admin": {"*"},
    "hr_admin": {"dashboard", "hr", "payroll", "reports", "documents"},
    "hr_manager": {"dashboard", "hr", "reports", "documents"},
    "payroll_manager": {"dashboard", "payroll", "reports", "documents"},
    "payroll_approver": {"dashboard", "payroll", "reports"},
    "payroll_payment": {"dashboard", "payroll"},
    "payroll_accounting": {"dashboard", "payroll", "accounting", "reports"},
    "sacco_officer": {"dashboard", "sacco", "documents"},
    "sacco_manager": {"dashboard", "sacco", "reports", "documents"},
    "sacco_kyc_approver": {"dashboard", "sacco"},
    "sacco_treasurer": {"dashboard", "sacco", "accounting", "reports"},
    "sacco_auditor": {"dashboard", "sacco", "reports"},
}


def has_module_permission(membership, module_key: str, action: str = "read") -> bool:
    """Check role action + module grant + optional branch scope at the route layer."""
    role = (getattr(membership, "role", "") or "").lower()
    module = (module_key or "").strip().lower()
    if action not in ROLE_PERMISSIONS.get(role, set()):
        return False
    allowed = ROLE_MODULES.get(role, set())
    return "*" in allowed or module in allowed


def require_module_permission(membership, module_key: str, action: str = "read") -> None:
    if not has_module_permission(membership, module_key, action):
        raise HTTPException(status_code=403, detail="Your organization role does not grant access to this module")
