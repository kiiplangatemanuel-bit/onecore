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



def worked_minutes(start, end) -> int:
    """Return completed whole minutes between UTC timestamps."""
    from datetime import timezone
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    elapsed = int((end - start).total_seconds() // 60)
    if elapsed < 0:
        raise ValueError("End timestamp cannot precede start timestamp")
    return elapsed
