from datetime import date, datetime, timedelta, timezone

from core.config.loader import get_policy

IST = timezone(timedelta(hours=5, minutes=30))  # India has no DST, so a fixed offset is exact


def today_ist() -> date:
    return datetime.now(IST).date()


def reference_date() -> date:
    """Policy-pinned date (for demos) or today in IST."""
    return get_policy().months.reference_date or today_ist()
