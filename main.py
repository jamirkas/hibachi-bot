"""
Hibachi Trading Bot — Entry Point.

Usage:
    python main.py --strategy grid
    python main.py --strategy mm
    python main.py --strategy grid,mm   # run both
    python main.py --config config.yaml
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from hibachi_bot import HibachiExchange, BotConfig
from hibachi_bot.strategies import get_strategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("hibachi")


def parse_args():
    p = argparse.ArgumentParser(description="Hibachi Trading Bot")
    p.add_argument("--config", default="config.yaml", help="Path to config file")
    p.add_argument("--strategy", default="grid", help="Strategy: grid, mm, or grid,mm")
    p.add_argument("--dry-run", action="store_true", help="Show what would be done, don't trade")
    return p.parse_args()


async def run_strategy(name: str, exchange: HibachiExchange, bot_config: BotConfig):
    strat_conf = next((s for s in bot_config.strategies if s.name == name), None)
    if strat_conf is None:
        logger.warning(f"No config for strategy '{name}', using defaults")
        from hibachi_bot.config import StrategyConfig
        strat_conf = StrategyConfig(name=name, symbol="BTC/USDT-P")

    cls = get_strategy(name)
    strategy = cls(exchange, strat_conf, bot_config.risk)
    logger.info(f"Starting {name} strategy...")
    await strategy.run_loop()


async def main():
    args = parse_args()

    if not Path(args.config).exists():
        logger.error(f"Config not found: {args.config}")
        logger.info("Copy config.example.yaml to config.yaml and fill in your keys.")
        sys.exit(1)

    bot_config = BotConfig.from_file(args.config)

    if not bot_config.api_key:
        logger.error("API key not set. Use HIBACHI_API_KEY env var or config.yaml")
        sys.exit(1)

    exchange = HibachiExchange(
        api_key=bot_config.api_key,
        secret_key=bot_config.secret_key,
        account_id=bot_config.account_id,
    )

    # Verify connection
    try:
        balance = exchange.balance()
        logger.info(f"Connected. Balance: {balance}")
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        sys.exit(1)

    strategy_names = [s.strip() for s in args.strategy.split(",")]
    tasks = [
        run_strategy(name, exchange, bot_config)
        for name in strategy_names
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
