from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.platform_admin import _validate_operation_transition


def record(status="draft", owner=10, payload=None):
    return SimpleNamespace(status=status, owner_user_id=owner, payload=payload or {})


def test_incident_state_machine_requires_ordered_transitions():
    item = record("draft")
    _validate_operation_transition("incidents", item, "investigating", 20)
    with pytest.raises(HTTPException) as invalid:
        _validate_operation_transition("incidents", item, "resolved", 20)
    assert invalid.value.status_code == 409


def test_incident_resolution_requires_independent_operator():
    item = record("monitoring", owner=10, payload={"last_transition_by": 20})
    with pytest.raises(HTTPException) as maker:
        _validate_operation_transition("incidents", item, "resolved", 10)
    assert maker.value.status_code == 403
    with pytest.raises(HTTPException) as previous_checker:
        _validate_operation_transition("incidents", item, "resolved", 20)
    assert previous_checker.value.status_code == 403
    _validate_operation_transition("incidents", item, "resolved", 30)


def test_maintenance_schedule_and_completion_require_independent_operators():
    item = record("draft", owner=10)
    with pytest.raises(HTTPException) as maker:
        _validate_operation_transition("maintenance", item, "scheduled", 10)
    assert maker.value.status_code == 403
    _validate_operation_transition("maintenance", item, "scheduled", 20)
    item.status = "scheduled"
    item.payload = {"last_transition_by": 20}
    with pytest.raises(HTTPException) as same_checker:
        _validate_operation_transition("maintenance", item, "in_progress", 20)
    assert same_checker.value.status_code == 403
    _validate_operation_transition("maintenance", item, "in_progress", 30)


def test_closed_operations_cannot_be_reopened_by_arbitrary_transition():
    item = record("completed", owner=10)
    with pytest.raises(HTTPException) as blocked:
        _validate_operation_transition("maintenance", item, "scheduled", 30)
    assert blocked.value.status_code == 409
