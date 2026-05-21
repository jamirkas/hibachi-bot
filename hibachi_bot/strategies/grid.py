"""
Grid trading strategy.

Places a ladder of limit orders above and below current price.
Profits from oscillation — buys low, sells high within the grid.
"""

import asyncio
import logging
from decimal import Decimal, ROUND_DOWN

from .base import BaseStrategy
from ..exchange import HibachiExchange
from ..config import StrategyConfig
from ..risk import RiskConfig

logger = logging.getLogger("hibachi.strategy.grid")


class GridStrategy(BaseStrategy):
    """
    Grid trading places equidistant limit orders forming a price ladder.

    Example for BTC/USDT-P @ 100,000 with 10 levels and 0.1% spread:
        Buys:  99,900 | 99,800 | 99,700 | 99,600 | 99,500
        Sells: 100,100 | 100,200 | 100,300 | 100,400 | 100,500

    When a buy fills, a corresponding sell goes above. When a sell fills,
    a corresponding buy goes below. Nets the spread each round-trip.
    """

    def __init__(self, exchange: HibachiExchange, config: StrategyConfig, risk: RiskConfig):
        super().__init__(exchange, config, risk)
        self._base_qty = Decimal(config.grid_base_qty)
        self._spread_pct = Decimal(str(config.grid_spread_pct))
        self._levels = config.grid_levels
        self._active_orders: dict[int, dict] = {}  # order_id → details

    async def setup(self) -> None:
        """Cancel all existing orders and place fresh grid."""
        symbol = self.config.symbol
        logger.info(f"[grid] Setting up grid on {symbol} — {self._levels} levels, {self._spread_pct}% spread")

        # Cancel everything
        self.exchange.cancel_all_orders(symbol)
        self._active_orders.clear()

        # Get mid-price
        book = self.exchange.order_book(symbol)
        if not book.bids or not book.asks:
            logger.warning("[grid] Empty order book, retrying...")
            return

        mid = Decimal(str((book.bids[0][0] + book.asks[0][0]) / 2)).quantize(Decimal("0.1"), ROUND_DOWN)
        logger.info(f"[grid] Mid-price: {mid}")

        # Place buy + sell ladders
        for i in range(self._levels):
            buy_price = mid * (Decimal("1") - self._spread_pct * Decimal(str(i + 1)) / Decimal("100"))
            sell_price = mid * (Decimal("1") + self._spread_pct * Decimal(str(i + 1)) / Decimal("100"))

            self._place("BUY", str(buy_price), symbol)
            self._place("SELL", str(sell_price), symbol)

        logger.info(f"[grid] Placed {len(self._active_orders)} orders")

    async def tick(self) -> None:
        """Check filled orders and replace them on the opposite side."""
        symbol = self.config.symbol
        open_orders = self.exchange.open_orders(symbol)

        current_ids = {o["orderId"] for o in open_orders}

        # Find filled/cancelled orders
        to_replace = []
        for oid, details in list(self._active_orders.items()):
            if oid not in current_ids:
                logger.info(f"[grid] Order {oid} filled ({details['side']} @ {details['price']})")
                to_replace.append(details)
                del self._active_orders[oid]

        # Replace filled orders on opposite side
        book = self.exchange.order_book(symbol)
        if not book.bids or not book.asks:
            return

        mid = (book.bids[0][0] + book.asks[0][0]) / 2

        for d in to_replace:
            filled_price = float(d["price"])
            if d["side"] == "BUY":
                # Buy filled → place sell above
                new_price = str(round(filled_price * (1 + self.config.grid_spread_pct / 100 * 2), 1))
                self._place("SELL", new_price, symbol)
            else:
                # Sell filled → place buy below
                new_price = str(round(filled_price * (1 - self.config.grid_spread_pct / 100 * 2), 1))
                self._place("BUY", new_price, symbol)

        await asyncio.sleep(1)  # Rate-limit guard

    def _place(self, side: str, price: str, symbol: str) -> None:
        """Place a limit order and track it."""
        try:
            resp = self.exchange.place_order(
                symbol=symbol,
                side=side,
                order_type="LIMIT",
                quantity=str(self._base_qty),
                price=price,
                time_in_force="GTC",
            )
            oid = resp.get("orderId")
            if oid:
                self._active_orders[oid] = {"side": side, "price": price}
        except Exception as e:
            logger.error(f"[grid] Failed to place {side} @ {price}: {e}")
