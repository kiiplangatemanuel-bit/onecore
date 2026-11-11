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
    "sacco_officer": {"read", "create"},
    "sacco_manager": {"read", "create", "update", "manage"},
    "sacco_kyc_approver": {"read", "manage"},
    "sacco_treasurer": {"read", "create"},
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
