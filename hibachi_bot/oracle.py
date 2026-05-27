"""
Binance WebSocket fair price oracle with fallback to Hibachi.

Connects to Binance WebSocket for real-time BTC/USDT price.
If Binance is unreachable, falls back to Hibachi REST API.

Usage (auto-enabled when BINANCE_ORACLE_ENABLED=1 in .env):
    python main.py  # oracle starts alongside strategies

Architecture:
    Binance WS → oracle_price in BotState
    Binance down → Hibachi REST API → oracle_price
    Both down → oracle_price = 0 → strategies use own order book
"""

import asyncio
import json
import logging
import time
from typing import Optional

logger = logging.getLogger("hibachi.oracle")

# How long to wait before declaring Binance dead and falling back
BINANCE_TIMEOUT = 15  # seconds
# How often to retry Binance after fallback
BINANCE_RETRY_INTERVAL = 60  # seconds
# Max age of Hibachi-fallback price before considering it stale
FALLBACK_MAX_AGE = 30  # seconds


class BinanceOracle:
    """WebSocket client for Binance ticker stream with Hibachi fallback."""

    WS_URL = "wss://stream.binance.com:9443/ws"

    def __init__(self, symbol: str = "btcusdt", exchange=None):
        """Create oracle for a given Binance symbol.

        Args:
            symbol: Binance symbol (lowercase, e.g. 'btcusdt')
            exchange: Optional HibachiExchange for REST API fallback
        """
        self.symbol = symbol.lower()
        self._exchange = exchange
        self._price: float = 0.0
        self._running = False
        self._binance_alive = False
        self._last_fallback_update: float = 0.0
        self._source: str = "none"  # "binance", "hibachi", "none"

    @property
    def price(self) -> float:
        """Current fair price from best available source."""
        return self._price

    @property
    def source(self) -> str:
        """Which source is providing the price."""
        return self._source

    @property
    def healthy(self) -> bool:
        """Whether we have a recent price from any source."""
        if self._source == "binance":
            return self._binance_alive
        if self._source == "hibachi":
            return (time.time() - self._last_fallback_update) < FALLBACK_MAX_AGE
        return False

    async def _fallback_to_hibachi(self, state=None) -> None:
        """Query Hibachi REST API for current price."""
        if not self._exchange:
            self._price = 0.0
            self._source = "none"
            return

        try:
            book = self._exchange.order_book("BTC/USDT-P", depth=1)
            if book.bids and book.asks:
                self._price = (book.bids[0][0] + book.asks[0][0]) / 2
                self._last_fallback_update = time.time()
                self._source = "hibachi"
                if state:
                    state.oracle_price = self._price
                logger.debug(f"🔮 Fallback price (Hibachi): ${self._price:.2f}")
        except Exception as e:
            logger.warning(f"🔮 Hibachi fallback failed: {e}")

    async def _binance_loop(self, state=None) -> None:
        """Connect to Binance WS and stream prices with reconnection."""
        import websockets

        stream = f"{self.symbol}@bookTicker"
        url = f"{self.WS_URL}/{stream}"

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    self._binance_alive = True
                    self._source = "binance"
                    logger.info(f"🔮 Oracle connected: Binance {stream}")
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
                self._binance_alive = False
                logger.warning(f"🔮 Binance disconnected: {e} — falling back to Hibachi")

                # Fallback loop: poll Hibachi REST while retrying Binance
                fallback_start = time.time()
                while self._running and not self._binance_alive:
                    await self._fallback_to_hibachi(state)

                    # Try reconnecting to Binance periodically
                    if time.time() - fallback_start > BINANCE_RETRY_INTERVAL:
                        logger.info("🔮 Retrying Binance connection...")
                        break  # Exit fallback loop, retry Binance in outer loop

                    await asyncio.sleep(5)

    async def run(self, state=None) -> None:
        """Run oracle (connect Binance WS, fallback to Hibachi on failure).

        Args:
            state: Optional BotState — updates state.oracle_price in real time.
        """
        self._running = True

        while self._running:
            await self._binance_loop(state)
            # If binance_loop exits (disconnected + retry timeout), loop back

    def stop(self):
        """Signal the oracle to stop."""
        self._running = False
