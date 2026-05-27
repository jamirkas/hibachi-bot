"""
Configuration loader with validation.

Secrets are loaded from environment variables FIRST, with config.yaml
as a fallback for backward compatibility.

Environment variables:
  HIBACHI_API_KEY       — API key (REQUIRED)
  HIBACHI_SECRET_KEY    — Secret key (REQUIRED)
  HIBACHI_ACCOUNT_ID    — Account ID (REQUIRED)
  DASHBOARD_PORT        — Web dashboard port (default: 8080)
  DASHBOARD_TOKEN       — Dashboard access token (default: none = open)
  DASHBOARD_HOST        — Dashboard bind address (default: 127.0.0.1)
  BINANCE_ORACLE_ENABLED — Enable Binance WS fair price (default: 0)
"""

import os
import yaml
import logging
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

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
    # Close Mode (from zo-market-maker-ts): when exposure > threshold, only open
    # one side to reduce risk.
    close_mode_enabled: bool = True
    close_mode_threshold_usd: float = 300.0
    close_mode_tight_spread: float = 0.03


@dataclass
class DisplayConfig:
    console_log: bool = True
    save_log: bool = True
    web_dashboard: bool = False
    web_port: int = 8080
    web_host: str = "127.0.0.1"
    web_token: str = ""


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
        """Load config from YAML, with env vars as primary source for secrets."""
        data = {}
        if os.path.exists(path):
            with open(path) as f:
                data = yaml.safe_load(f) or {}

        # Secrets: env vars FIRST, config.yaml as fallback
        api_key = os.getenv("HIBACHI_API_KEY") or data.get("api_key", "")
        secret_key = os.getenv("HIBACHI_SECRET_KEY") or data.get("secret_key", "")
        account_id = int(os.getenv("HIBACHI_ACCOUNT_ID") or data.get("account_id", 0))

        # Dashboard: env vars override config
        display_data = data.get("display", {})
        display = DisplayConfig(
            console_log=display_data.get("console_log", True),
            save_log=display_data.get("save_log", True),
            web_dashboard=display_data.get("web_dashboard", False),
            web_port=int(os.getenv("DASHBOARD_PORT") or display_data.get("web_port", 8080)),
            web_host=os.getenv("DASHBOARD_HOST") or display_data.get("web_host", "127.0.0.1"),
            web_token=os.getenv("DASHBOARD_TOKEN") or display_data.get("web_token", ""),
        )

        return cls(
            api_key=api_key,
            secret_key=secret_key,
            account_id=account_id,
            risk=RiskConfig(**data.get("risk", {})),
            active_strategies=data.get("active_strategies", ["grid"]),
            grid=GridConfig(**data.get("grid", {})),
            mm=MMConfig(**data.get("mm", {})),
            display=display,
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.api_key:
            errors.append("api_key is required (set HIBACHI_API_KEY in .env)")
        if not self.secret_key:
            errors.append("secret_key is required (set HIBACHI_SECRET_KEY in .env)")
        if not self.account_id:
            errors.append("account_id is required (set HIBACHI_ACCOUNT_ID in .env)")
        if not self.active_strategies:
            errors.append("active_strategies cannot be empty")
        return errors
