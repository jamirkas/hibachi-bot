"""
Hibachi Trading Bot — Entry Point with Dashboard.

Quick start:
    python setup.py            # Interactive config wizard
    python main.py             # Run bot + dashboard (if enabled)

Dashboard: http://localhost:8080 (when enabled)
"""

import argparse
import asyncio
import logging
import os
import sys
import json
from pathlib import Path

from hibachi_bot import HibachiExchange, BotConfig
from hibachi_bot.strategies.grid import GridStrategy
from hibachi_bot.strategies.mm import MarketMakingStrategy
from hibachi_bot.dashboard import BotState, create_dashboard

# ── Logging ──────────────────────────────────────────

LOG_FORMAT = "%(asctime)s  %(levelname)-7s  %(message)s"
LOG_DATE = "%H:%M:%S"

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATE)
logger = logging.getLogger("hibachi")

file_handler = None


def setup_file_logging():
    global file_handler
    path = Path("hibachi-bot.log")
    file_handler = logging.FileHandler(path)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE))
    file_handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(file_handler)
    logger.info(f"Logging to {path.absolute()}")


# ── CLI ──────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Hibachi Trading Bot")
    p.add_argument("--config", default="config.yaml", help="Config file path")
    p.add_argument("--strategy", default="", help="Override: grid, mm, or grid,mm")
    p.add_argument("--dashboard", type=int, default=0, help="Override dashboard port (0=use config)")
    p.add_argument("--dry-run", action="store_true", help="Show config, don't trade")
    return p.parse_args()


# ── Banner ───────────────────────────────────────────

BANNER = """
╔═══════════════════════════════════╗
║   🥩  HIBACHI TRADING BOT v2     ║
║   Grid + Market Maker            ║
║   0% maker fees = pure spread    ║
╚═══════════════════════════════════╝
"""


# ── State sync helpers ───────────────────────────────

async def state_sync(state: BotState, exchange: HibachiExchange, symbol: str, interval: float = 5.0):
    """Periodically sync exchange state to dashboard state."""
    while state.running:
        try:
            bal = exchange.balance()
            state.balance = float(bal.get("available", bal.get("balance", 0)))
            state.positions = exchange.positions()
            state.active_orders = exchange.open_orders(symbol)

            book = exchange.order_book(symbol, depth=1)
            if book.bids and book.asks:
                state.mark_price = (book.bids[0][0] + book.asks[0][0]) / 2
        except Exception as e:
            logger.debug(f"State sync error: {e}")

        await asyncio.sleep(interval)


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

    if config.display.save_log:
        setup_file_logging()

    # ── Shared State ──
    state = BotState(
        running=True,
        account_id=config.account_id,
        started_at=__import__("time").time(),
    )

    # ── Dashboard ──
    dashboard_port = args.dashboard or config.display.web_port
    if config.display.web_dashboard or args.dashboard:
        create_dashboard(state, dashboard_port)
        print(f"📊 Dashboard: http://localhost:{dashboard_port}")

    # ── Connect ──
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

    # ── Strategies ──
    strategy_names = [s.strip() for s in args.strategy.split(",")] if args.strategy else config.active_strategies
    state.strategies = strategy_names

    tasks = []

    for name in strategy_names:
        if name == "grid" and "grid" in config.active_strategies:
            strategy = GridStrategy(exchange, config.grid, config.risk)
            state.symbol = config.grid.symbol
            logger.info(f"🧱 Grid: {config.grid.grid_count}×2 levels, "
                         f"step={config.grid.step_pct}%, "
                         f"size=${config.grid.order_size_usdt}, "
                         f"TP={config.grid.take_profit_pct}%, SL={config.grid.stop_loss_pct}%")
            tasks.append(strategy.run_loop())

        elif name == "mm" and "mm" in config.active_strategies:
            strategy = MarketMakingStrategy(exchange, config.mm, config.risk)
            state.symbol = config.mm.symbol
            logger.info(f"📊 MM: spread={config.mm.spread_pct}%, "
                         f"order=${config.mm.order_size_usdt}")
            tasks.append(strategy.run_loop())

        else:
            logger.warning(f"Skipping '{name}' — not in active_strategies")

    if not tasks:
        logger.error("No strategies to run.")
        sys.exit(1)

    # State sync alongside strategies
    symbol = state.symbol
    tasks.append(state_sync(state, exchange, symbol))

    print("─" * 40)
    print("🤖 Bot running. Press Ctrl+C to stop.")
    print("─" * 40)

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        state.running = False
        logger.info("Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
