"""
Configuration loader.
"""

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path

from .risk import RiskConfig


@dataclass
class StrategyConfig:
    name: str                     # "grid" | "mm"
    symbol: str                   # e.g. "BTC/USDT-P"
    enabled: bool = True

    # Grid params
    grid_levels: int = 10
    grid_spread_pct: float = 0.1  # % between grid levels
    grid_base_qty: str = "0.001"  # base qty per level

    # Market making params
    mm_spread: float = 0.05       # % from mid-price
    mm_order_qty: str = "0.001"
    mm_refresh_sec: float = 2.0   # re-evaluate orders every N seconds


@dataclass
class BotConfig:
    api_key: str = ""
    secret_key: str = ""
    account_id: int = 0

    risk: RiskConfig = field(default_factory=lambda: RiskConfig(
        max_position_size=5000.0,
        max_total_exposure=10000.0,
        stop_loss_pct=0.05,
        max_grid_levels=20,
        min_order_size=10.0,
        max_open_orders=50,
    ))

    strategies: list[StrategyConfig] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str) -> "BotConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(
            api_key=data.get("api_key", os.getenv("HIBACHI_API_KEY", "")),
            secret_key=data.get("secret_key", os.getenv("HIBACHI_SECRET_KEY", "")),
            account_id=data.get("account_id", int(os.getenv("HIBACHI_ACCOUNT_ID", "0"))),
            risk=RiskConfig(**data.get("risk", {})),
            strategies=[StrategyConfig(**s) for s in data.get("strategies", [])],
        )
