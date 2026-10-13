"""Versioned economics of supported full-size research contracts.

Commission remains an explicit round-trip per-contract experiment input.
Micro contracts require their own data/rollover validation before admission.
"""
from dataclasses import asdict, dataclass

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Instrument:
    symbol: str
    tick_size: float
    tick_value: float
    currency: str = 'USD'
    timezone: str = 'America/New_York'


INSTRUMENTS = {s.symbol: s for s in (Instrument('NQ', .25, 5.), Instrument('ES', .25, 12.5))}


def instrument_spec(symbol):
    try:
        return INSTRUMENTS[symbol]
    except (KeyError, TypeError):
        raise ValueError(f'Strumento non supportato: {symbol}; ammessi NQ/ES full-size, non MNQ/MES') from None


def instrument_metadata(symbol):
    return dict(schema_version=SCHEMA_VERSION, **asdict(instrument_spec(symbol)),
                commission_basis='round_trip_per_contract')
