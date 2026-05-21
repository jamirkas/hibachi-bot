"""
Hibachi Trading Bot — Entry Point.

Quick start:
    python setup.py            # Interactive config wizard
    python main.py             # Run all enabled strategies
    python main.py --strategy grid    # Grid only
    python main.py --strategy mm      # Market maker only

Or with env vars:
    export HIBACHI_API_KEY=...
    export HIBACHI_SECRET_KEY=...
    export HIBACHI_ACCOUNT_ID=...
    python main.py
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

from hibachi_bot import HibachiExchange, BotConfig
from hibachi_bot.strategies.grid import GridStrategy
from hibachi_bot.strategies.mm import MarketMakingStrategy

# ── Logging ──────────────────────────────────────────

LOG_FORMAT = "%(asctime)s  %(levelname)-7s  %(message)s"
LOG_DATE = "%H:%M:%S"

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATE)

# File logger
file_handler = None


def setup_file_logging():
    global file_handler
    path = Path("hibachi-bot.log")
    file_handler = logging.FileHandler(path)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE))
    file_handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(file_handler)
    logging.getLogger("hibachi").info(f"Logging to {path.absolute()}")


# ── CLI ──────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Hibachi Trading Bot")
    p.add_argument("--config", default="config.yaml", help="Config file path")
    p.add_argument("--strategy", default="", help="Override: grid, mm, or grid,mm")
    p.add_argument("--dry-run", action="store_true", help="Show config, don't trade")
    return p.parse_args()


# ── Banner ───────────────────────────────────────────

BANNER = """
╔═══════════════════════════════════╗
║   🥩  HIBACHI TRADING BOT        ║
║   Grid + Market Maker            ║
║   0% maker fees = pure spread    ║
╚═══════════════════════════════════╝
"""


# ── Main ─────────────────────────────────────────────

async def main():
    print(BANNER)
    args = parse_args()

    # Check config
    if not Path(args.config).exists():
        print(f"❌ Config not found: {args.config}")
        print("   Run: python setup.py")
        sys.exit(1)

    config = BotConfig.from_file(args.config)
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"❌ {e}")
        print("   Run: python setup.py")
        sys.exit(1)

    if args.dry_run:
        print("✅ Config valid. Would run:")
        for s in config.active_strategies:
            print(f"   • {s}")
        sys.exit(0)

    # Logging
    if config.display.save_log:
        setup_file_logging()

    logger = logging.getLogger("hibachi")
    logger.info(f"Starting — strategies: {config.active_strategies}")
    logger.info(f"Account ID: {config.account_id}")
    logger.info(f"Max exposure: ${config.risk.max_total_exposure:,.0f}")

    # Connect
    exchange = HibachiExchange(
        api_key=config.api_key,
        secret_key=config.secret_key,
        account_id=config.account_id,
    )

    try:
        balance = exchange.balance()
        logger.info(f"✅ Connected. Balance: {balance}")
    except Exception as e:
        logger.error(f"❌ Connection failed: {e}")
        sys.exit(1)

    # Resolve strategies
    strategy_names = [s.strip() for s in args.strategy.split(",")] if args.strategy else config.active_strategies

    tasks = []
    for name in strategy_names:
        if name == "grid" and "grid" in config.active_strategies:
            strategy = GridStrategy(exchange, config.grid, config.risk)
            logger.info(f"🧱 Grid: {config.grid.grid_count}×2 levels, "
                         f"step={config.grid.step_pct}%, "
                         f"size=${config.grid.order_size_usdt}, "
                         f"TP={config.grid.take_profit_pct}%, SL={config.grid.stop_loss_pct}%")
            tasks.append(strategy.run_loop())

        elif name == "mm" and "mm" in config.active_strategies:
            strategy = MarketMakingStrategy(exchange, config.mm, config.risk)
            logger.info(f"📊 MM: spread={config.mm.spread_pct}%, "
                         f"order=${config.mm.order_size_usdt}")
            tasks.append(strategy.run_loop())

        else:
            logger.warning(f"Skipping '{name}' — not in active_strategies")

    if not tasks:
        logger.error("No strategies to run.")
        sys.exit(1)

    print("─" * 40)
    print("🤖 Bot running. Press Ctrl+C to stop.")
    print("─" * 40)

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
