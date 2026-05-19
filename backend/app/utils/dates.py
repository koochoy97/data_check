"""Helpers de fecha/hora canónicos. Perú es UTC-5 sin DST."""
from datetime import date, datetime, timedelta, timezone


PERU_UTC_OFFSET = timezone(timedelta(hours=-5))


def now_peru() -> datetime:
    """Datetime actual en timezone Perú (UTC-5)."""
    return datetime.now(PERU_UTC_OFFSET)


def today_peru() -> date:
    """Fecha actual en Perú. Usar siempre que se generen o se busquen archivos diarios."""
    return now_peru().date()


def today_peru_iso() -> str:
    """Fecha actual Perú en formato 'YYYY-MM-DD'."""
    return today_peru().isoformat()
