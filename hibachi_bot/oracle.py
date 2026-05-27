"""
Binance WebSocket fair price oracle.

Connects to Binance WebSocket for real-time BTC/USDT price.
Provides a more reliable mid-price than a single DEX order book.

Usage (auto-enabled when BINANCE_ORACLE_ENABLED=1 in .env):
    python main.py  # oracle will start alongside strategies

Architecture:
    Binance WS → oracle_price stored in BotState.oracle_price
    Strategies can use state.oracle_price instead of exchange order book mid
"""

import asyncio
import json
import logging
from typing import Optional

logger = logging.getLogger("hibachi.oracle")


class BinanceOracle:
    """WebSocket client for Binance ticker stream (BTC/USDT by default)."""

    WS_URL = "wss://stream.binance.com:9443/ws"

    def __init__(self, symbol: str = "btcusdt"):
        """Create oracle for a given Binance symbol (lowercase, e.g. 'btcusdt')."""
        self.symbol = symbol.lower()
        self._price: float = 0.0
        self._running = False

    @property
    def price(self) -> float:
        """Current best bid/ask mid from Binance."""
        return self._price

    async def run(self, state=None) -> None:
        """Connect to Binance WebSocket and stream book ticker indefinitely.

        Args:
            state: Optional BotState — updates state.oracle_price in real time.
        """
        self._running = True

        while self._running:
            try:
                import websockets
            except ImportError:
                logger.error("websockets not installed — oracle disabled. pip install websockets")
                return

            stream = f"{self.symbol}@bookTicker"
            url = f"{self.WS_URL}/{stream}"

            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    logger.info(f"🔮 Oracle connected: {stream}")
                    while self._running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=30)
                            data = json.loads(msg)
                            bid = float(data.get("b", 0))
                            ask = float(data.get("a", 0))
                            if bid > 0 and ask > 0:
                                self._price = (bid + ask) / 2
                                if state:
                                    state.oracle_price = self._price
                        except asyncio.TimeoutError:
                            continue
                        except Exception as e:
                            logger.debug(f"Oracle message error: {e}")
                            continue
            except Exception as e:
                logger.warning(f"Oracle disconnected: {e} — reconnecting in 5s...")
                await asyncio.sleep(5)

    def stop(self):
        """Signal the oracle to stop."""
        self._running = False
