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


def build_pipeline_analytics(leads, quotes):
    """Build deterministic, currency-separated CRM performance metrics."""
    from collections import defaultdict
    from decimal import Decimal

    probabilities = {
        "new": Decimal("0.10"), "qualified": Decimal("0.25"),
        "proposal": Decimal("0.50"), "negotiation": Decimal("0.75"),
        "won": Decimal("1.00"), "lost": Decimal("0"),
    }
    counts = {"total": len(leads), "open": 0, "won": 0, "lost": 0}
    pipeline = defaultdict(lambda: {
        "lead_count": 0, "open_pipeline_value": Decimal("0"),
        "weighted_open_value": Decimal("0"), "won_value": Decimal("0"),
        "lost_value": Decimal("0"), "stages": defaultdict(
            lambda: {"count": 0, "value": Decimal("0"), "weighted_value": Decimal("0")})
    })
    for lead in leads:
        value = Decimal(lead.estimated_value)
        bucket = pipeline[lead.currency]
        bucket["lead_count"] += 1
        stage = bucket["stages"][lead.stage]
        stage["count"] += 1
        stage["value"] += value
        stage["weighted_value"] += value * probabilities[lead.stage]
        if lead.stage == "won":
            counts["won"] += 1
            bucket["won_value"] += value
        elif lead.stage == "lost":
            counts["lost"] += 1
            bucket["lost_value"] += value
        else:
            counts["open"] += 1
            bucket["open_pipeline_value"] += value
            bucket["weighted_open_value"] += value * probabilities[lead.stage]
    closed = counts["won"] + counts["lost"]
    win_rate = ((Decimal(counts["won"]) * Decimal("100") / Decimal(closed)).quantize(Decimal("0.01"))
                if closed else None)

    quote_buckets = defaultdict(lambda: {
        "count": 0, "draft": 0, "issued": 0, "accepted": 0,
        "rejected": 0, "expired": 0, "accepted_value": Decimal("0")})
    for quote in quotes:
        bucket = quote_buckets[quote.currency]
        bucket["count"] += 1
        bucket[quote.status] += 1
        if quote.status == "accepted":
            bucket["accepted_value"] += Decimal(quote.total)

    money = lambda value: str(value.quantize(Decimal("0.01")))
    return {
        "lead_summary": {**counts, "closed": closed,
                         "win_rate_percent": str(win_rate) if win_rate is not None else None},
        "pipeline_by_currency": [{
            "currency": currency, "lead_count": data["lead_count"],
            "open_pipeline_value": money(data["open_pipeline_value"]),
            "weighted_open_value": money(data["weighted_open_value"]),
            "won_value": money(data["won_value"]), "lost_value": money(data["lost_value"]),
            "stages": [{"stage": stage, "count": item["count"],
                "value": money(item["value"]), "weighted_value": money(item["weighted_value"])}
                for stage, item in sorted(data["stages"].items())]
        } for currency, data in sorted(pipeline.items())],
        "quotes_by_currency": [{
            "currency": currency, **{key: data[key] for key in
                ("count", "draft", "issued", "accepted", "rejected", "expired")},
            "accepted_value": money(data["accepted_value"])
        } for currency, data in sorted(quote_buckets.items())],
        "method": "Descriptive historical counts and fixed stage probabilities; not a statistical prediction"
    }
