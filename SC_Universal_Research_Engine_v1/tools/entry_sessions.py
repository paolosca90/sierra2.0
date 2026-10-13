"""Entry-only windows in New York, evaluated at the actual simulated fill time."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import numpy as np


def validate_windows(windows):
    if not isinstance(windows, list):
        raise ValueError('entry_windows: lista di intervalli in secondi New York')
    for window in windows:
        if not isinstance(window, list) or len(window) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in window):
            raise ValueError('entry_windows: ogni intervallo richiede due interi')
        if not 0 <= window[0] < window[1] <= 86400:
            raise ValueError('entry_windows: 0 <= inizio < fine <= 86400; dividere intervalli notturni')


def entry_mask(times_us, windows):
    validate_windows(windows)
    if not windows:
        return np.ones(len(times_us), dtype=bool)
    times = np.asarray(times_us, dtype=np.int64)
    hours, inverse = np.unique(times // 3_600_000_000, return_inverse=True)
    epoch = datetime(1899, 12, 30, tzinfo=timezone.utc)
    ny = ZoneInfo('America/New_York')
    local_hours = np.array([(epoch + timedelta(hours=int(hour))).astimezone(ny).hour for hour in hours])
    clock_us = local_hours[inverse] * 3_600_000_000 + times % 3_600_000_000
    allowed = np.zeros(len(times), dtype=bool)
    for start, end in windows:
        allowed |= (clock_us >= start * 1_000_000) & (clock_us < end * 1_000_000)
    return allowed
