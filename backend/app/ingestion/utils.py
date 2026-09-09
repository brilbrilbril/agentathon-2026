import math
import re
from datetime import date, datetime


def normalise_header(name: str) -> str:
    """Strip and collapse internal whitespace. DESC has genuine double-space
    column names like 'Individual  Address City'."""
    return re.sub(r"\s+", " ", str(name).strip())


def none_if_blank(value):
    if value is None:
        return None
    # pandas leaves empty cells as float NaN even with dtype=str
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def safe_date(value) -> date | None:
    """Handles WBS YYYYMMDD strings, '00000000' nulls, COT datetimes/strings,
    and PDF DD/MM/YYYY strings."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text or text == "00000000":
        return None

    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None

    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", text):
        try:
            return datetime.strptime(text, "%d/%m/%Y").date()
        except ValueError:
            return None

    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    return None


def safe_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    d = safe_date(value)
    return datetime(d.year, d.month, d.day) if d else None
