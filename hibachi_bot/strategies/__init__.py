"""
Strategy registry.
"""

from .base import BaseStrategy
from .grid import GridStrategy
from .mm import MarketMakingStrategy


STRATEGIES = {
    "grid": GridStrategy,
    "mm": MarketMakingStrategy,
}


def get_strategy(name: str) -> type[BaseStrategy]:
    if name not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGIES)}")
    return STRATEGIES[name]
