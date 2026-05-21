"""
Setup wizard — interactive configuration for non-technical users.

Usage: python setup.py
"""

import os
import sys
import yaml
from pathlib import Path


def ask(prompt: str, default: str = "") -> str:
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"{prompt}: ").strip()


def ask_float(prompt: str, default: float) -> float:
    val = ask(prompt, str(default))
    try:
        return float(val)
    except ValueError:
        print(f"  ⚠ Invalid number, using default: {default}")
        return default


def ask_int(prompt: str, default: int) -> int:
    val = ask(prompt, str(default))
    try:
        return int(val)
    except ValueError:
        print(f"  ⚠ Invalid number, using default: {default}")
        return default


def ask_yesno(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    val = ask(f"{prompt} ({d})", "Y" if default else "N")
    return val.lower() in ("y", "yes", "")


def main():
    print("""
╔══════════════════════════════════════════╗
║     🥩 Hibachi Trading Bot — Setup       ║
╚══════════════════════════════════════════╝

This wizard will create config.yaml for you.
You'll need:
  • Hibachi account (sign up at hibachi.xyz)
  • API Key + Secret Key (from Settings → API Keys)
  • Account ID (shown on API Keys page)

Let's go!
""")

    config = {
        "api_key": ask("API Key"),
        "secret_key": ask("Secret Key"),
        "account_id": ask_int("Account ID", 0),
        "risk": {
            "max_total_exposure": ask_float("  Max total USDT at risk", 5000.0),
            "max_position_per_side": ask_float("  Max USDT per buy/sell side", 1000.0),
        },
    }

    # Strategy selection
    print("\n--- Strategy Selection ---")
    print("  1. Grid Trading (best for sideways/volatile markets)")
    print("  2. Market Making (best for tight spreads, 0% maker fee)")
    print("  3. Both")

    choice = ask("Choose strategy", "1")
    strategies = []
    if choice in ("1", "3"):
        strategies.append("grid")
    if choice in ("2", "3"):
        strategies.append("mm")
    config["active_strategies"] = strategies

    if "grid" in strategies:
        print("\n--- Grid Strategy ---")
        config["grid"] = {
            "symbol": ask("  Trading pair", "BTC/USDT-P"),
            "enabled": True,
            "grid_count": ask_int("  Number of grid levels (each side)", 10),
            "step_pct": ask_float("  Distance between levels (%)", 0.15),
            "order_size_usdt": ask_float("  USDT per order", 50.0),
            "take_profit_pct": ask_float("  Take-profit (%)", 0.3),
            "stop_loss_pct": ask_float("  Stop-loss (%)", 2.0),
            "trailing_tp": ask_yesno("  Trailing take-profit", False),
            "refresh_sec": ask_float("  Refresh interval (seconds)", 5.0),
        }

    if "mm" in strategies:
        print("\n--- Market Maker Strategy ---")
        config["mm"] = {
            "symbol": ask("  Trading pair", "BTC/USDT-P"),
            "enabled": True,
            "spread_pct": ask_float("  Bid/Ask spread from mid-price (%)", 0.05),
            "min_spread_pct": ask_float("  Minimum spread (%)", 0.02),
            "max_spread_pct": ask_float("  Maximum spread (%)", 0.2),
            "order_size_usdt": ask_float("  USDT per order", 100.0),
            "max_orders_per_side": ask_int("  Max orders per side", 3),
            "max_long_usdt": ask_float("  Max long exposure (USDT)", 500.0),
            "max_short_usdt": ask_float("  Max short exposure (USDT)", 500.0),
            "cancel_on_price_move_pct": ask_float("  Cancel if price moves > %?", 1.0),
            "refresh_sec": ask_float("  Refresh interval (seconds)", 2.0),
            "adaptive_spread": ask_yesno("  Auto-adjust spread to volatility", True),
        }

    config["display"] = {
        "console_log": True,
        "save_log": True,
        "web_dashboard": ask_yesno("\nEnable web dashboard on port 8080?", False),
        "web_port": 8080,
    }

    # Write config
    path = Path("config.yaml")
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"\n✅ Config saved to {path.absolute()}")
    print("   Run: python main.py")
    print("   Or:  python main.py --strategy grid    (grid only)")
    print("   Or:  python main.py --strategy mm      (market maker only)")


if __name__ == "__main__":
    main()
