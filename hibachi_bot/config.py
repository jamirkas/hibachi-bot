"""
Configuration loader with validation.
"""

import os
import yaml
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("hibachi.config")


@dataclass
class RiskConfig:
    max_total_exposure: float = 5000.0
    max_position_per_side: float = 1000.0


@dataclass
class GridConfig:
    symbol: str = "BTC/USDT-P"
    enabled: bool = True
    grid_count: int = 10
    step_pct: float = 0.15
    order_size_usdt: float = 50.0
    take_profit_pct: float = 0.3
    stop_loss_pct: float = 2.0
    trailing_tp: bool = False
    refresh_sec: float = 5.0


@dataclass
class MMConfig:
    symbol: str = "BTC/USDT-P"
    enabled: bool = True
    spread_pct: float = 0.05
    min_spread_pct: float = 0.02
    max_spread_pct: float = 0.2
    order_size_usdt: float = 100.0
    max_orders_per_side: int = 3
    max_long_usdt: float = 500.0
    max_short_usdt: float = 500.0
    cancel_on_price_move_pct: float = 1.0
    refresh_sec: float = 2.0
    adaptive_spread: bool = True


@dataclass
class DisplayConfig:
    console_log: bool = True
    save_log: bool = True
    web_dashboard: bool = False
    web_port: int = 8080


@dataclass
class BotConfig:
    api_key: str = ""
    secret_key: str = ""
    account_id: int = 0
    risk: RiskConfig = field(default_factory=RiskConfig)
    active_strategies: list[str] = field(default_factory=lambda: ["grid"])
    grid: GridConfig = field(default_factory=GridConfig)
    mm: MMConfig = field(default_factory=MMConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)

    @classmethod
    def from_file(cls, path: str) -> "BotConfig":
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        return cls(
            api_key=data.get("api_key", os.getenv("HIBACHI_API_KEY", "")),
            secret_key=data.get("secret_key", os.getenv("HIBACHI_SECRET_KEY", "")),
            account_id=data.get("account_id", int(os.getenv("HIBACHI_ACCOUNT_ID", "0"))),
            risk=RiskConfig(**data.get("risk", {})),
            active_strategies=data.get("active_strategies", ["grid"]),
            grid=GridConfig(**data.get("grid", {})),
            mm=MMConfig(**data.get("mm", {})),
            display=DisplayConfig(**data.get("display", {})),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.api_key:
            errors.append("api_key is required")
        if not self.secret_key:
            errors.append("secret_key is required")
        if not self.account_id:
            errors.append("account_id is required (find in Hibachi API settings)")
        if not self.active_strategies:
            errors.append("active_strategies cannot be empty")
        return errors
