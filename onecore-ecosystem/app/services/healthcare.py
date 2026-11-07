"""Healthcare scheduling state rules."""


def validate_appointment_transition(current: str, target: str) -> None:
    transitions = {
        "scheduled": {"checked_in", "cancelled", "no_show"},
        "checked_in": {"completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
        "no_show": set(),
    }
    if target not in transitions.get(current, set()):
        from fastapi import HTTPException
        raise HTTPException(409, f"Invalid appointment transition: {current} -> {target}")
