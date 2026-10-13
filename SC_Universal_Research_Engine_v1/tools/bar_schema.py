"""Shared time-bar validation for the API, reader and aggregation cache."""


def validate_bar_seconds(seconds):
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 1 or 86400 % seconds:
        raise ValueError('bar_seconds: intero positivo che deve dividere 86400 secondi')
    return seconds
