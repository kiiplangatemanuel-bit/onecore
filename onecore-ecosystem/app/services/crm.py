"""CRM sales pipeline state rules."""
from fastapi import HTTPException

LEAD_STAGES = {"new", "qualified", "proposal", "negotiation", "won", "lost"}
_ALLOWED = {
    "new": {"qualified", "lost"},
    "qualified": {"proposal", "negotiation", "lost"},
    "proposal": {"negotiation", "won", "lost"},
    "negotiation": {"proposal", "won", "lost"},
    "won": set(),
    "lost": {"new"},
}


def validate_stage_transition(current: str, target: str) -> None:
    if target not in LEAD_STAGES or target not in _ALLOWED.get(current, set()):
        raise HTTPException(409, f"Lead cannot move from {current} to {target}")
