"""Deterministic CRM forecast calculations and calendar-period helpers."""
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
STAGES = {"new", "qualified", "proposal", "negotiation", "won", "lost"}
DEFAULT_PROBABILITIES = {"new": 10, "qualified": 25, "proposal": 50, "negotiation": 75, "won": 100, "lost": 0}
DEFAULT_MULTIPLIERS = {"best_case": 1.0, "expected": 1.0, "worst_case": 0.5}
CENT = Decimal("0.01")
def period_bounds(period_type, start):
    if period_type == "month":
        first=date(start.year,start.month,1);last=date(start.year,start.month,monthrange(start.year,start.month)[1])
    elif period_type == "quarter":
        month=((start.month-1)//3)*3+1;first=date(start.year,month,1);end_month=month+2
        last=date(start.year,end_month,monthrange(start.year,end_month)[1])
    elif period_type == "year": first,last=date(start.year,1,1),date(start.year,12,31)
    else: raise ValueError("period_type must be month, quarter or year")
    return first,last
def calculate_scenarios(leads, probabilities=None, multipliers=None):
    probs={**DEFAULT_PROBABILITIES,**(probabilities or {})};mult={**DEFAULT_MULTIPLIERS,**(multipliers or {})}
    open_leads=[x for x in leads if x.stage not in {"won","lost"}]
    gross=sum((Decimal(str(x.estimated_value)) for x in open_leads),Decimal("0"))
    weighted=sum((Decimal(str(x.estimated_value))*Decimal(str(
        x.probability_override if x.probability_override is not None else probs.get(x.stage,0)))/Decimal("100")
        for x in open_leads),Decimal("0"))
    return {"best_case":(gross*Decimal(str(mult["best_case"]))).quantize(CENT,rounding=ROUND_HALF_UP),
        "expected":(weighted*Decimal(str(mult["expected"]))).quantize(CENT,rounding=ROUND_HALF_UP),
        "worst_case":(weighted*Decimal(str(mult["worst_case"]))).quantize(CENT,rounding=ROUND_HALF_UP)}
