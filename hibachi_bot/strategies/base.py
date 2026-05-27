"""
Base strategy class.
"""

import logging
from abc import ABC, abstractmethod

from ..exchange import HibachiExchange

logger = logging.getLogger("hibachi.strategy")


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    def __init__(self, exchange: HibachiExchange, config, risk):
        self.exchange = exchange
        self.config = config
        self.risk = risk
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @abstractmethod
    async def setup(self) -> None:
        """Initialize strategy state, cancel stale orders, sync positions."""
        ...

    @abstractmethod
    async def tick(self) -> None:
        """Single iteration — check market, adjust orders."""
        ...

    async def start(self) -> None:
        self._running = True
        logger.info(f"[{self.config.name}] Started on {self.config.symbol}")
        await self.setup()

    async def stop(self) -> None:
        self._running = False
        logger.info(f"[{self.config.name}] Stopped")

    async def run_loop(self) -> None:
        """Main loop — override for custom scheduling."""
        await self.start()
        try:
            while self._running:
                await self.tick()
        finally:
            await self.stop()
