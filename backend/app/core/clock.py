from datetime import datetime, timezone


def utcnow() -> datetime:
    """Single seam for 'the current instant' across the app.

    Exists so tests can monkeypatch this one function to a fixed instant
    instead of every module reaching for `datetime.now(timezone.utc)`
    directly. Without it, any test that builds time-relative fixtures (e.g.
    a procurement slot "ending in 3 hours") is exposed to real wall-clock
    edge cases - most notably the UTC midnight boundary, where a slot's
    start and end time can silently fall on different calendar dates even
    though `ProcurementSlot` only stores one `slot_date` shared by both
    (see `_slot_datetime` in app/services/scheduling.py and
    app/repositories/procurement.py, which always combine a single date
    with each time field). See tests/test_scheduling.py's `frozen_clock`
    fixture for how this is exercised.
    """
    return datetime.now(timezone.utc)
