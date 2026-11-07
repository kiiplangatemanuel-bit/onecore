"""HR date calculations shared by leave workflows."""
from datetime import date, timedelta


def business_days(start: date, end: date) -> int:
    """Count weekdays inclusively; public holidays are not subtracted."""
    if end < start:
        raise ValueError("End date cannot precede start date")
    total = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            total += 1
        current += timedelta(days=1)
    return total
