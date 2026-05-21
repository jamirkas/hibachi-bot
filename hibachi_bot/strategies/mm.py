"""
Market making strategy.

Maintains bid and ask limit orders around the mid-price.
Profits from the spread — with 0% maker fees on Hibachi,
every filled round-trip is pure profit.
"""

import asyncio
import logging
from decimal import Decimal, ROUND_DOWN

from .base import BaseStrategy
from ..exchange import HibachiExchange
from ..config import StrategyConfig
from ..risk import RiskConfig

logger = logging.getLogger("hibachi.strategy.mm")


class MarketMakingStrategy(BaseStrategy):
    """
    Simple market maker: places 1 bid and 1 ask around mid-price.
    Refreshes every N seconds to track the market.

    With Hibachi's 0% maker fee, the spread is pure profit.
    """

    def __init__(self, exchange: HibachiExchange, config: StrategyConfig, risk: RiskConfig):
        super().__init__(exchange, config, risk)
        self._qty = Decimal(config.mm_order_qty)
        self._spread = Decimal(str(config.mm_spread))
        self._refresh_sec = config.mm_refresh_sec
        self._bid_id: int | None = None
        self._ask_id: int | None = None

    async def setup(self) -> None:
        """Cancel existing and prepare."""
        symbol = self.config.symbol
        self.exchange.cancel_all_orders(symbol)
        self._bid_id = None
        self._ask_id = None

    async def tick(self) -> None:
        """Read order book, place/refresh bid & ask."""
        symbol = self.config.symbol

        # Cancel stale orders
        if self._bid_id:
            try:
                self.exchange.cancel_order(self._bid_id)
            except Exception:
                pass
        if self._ask_id:
            try:
                self.exchange.cancel_order(self._ask_id)
            except Exception:
                pass

        # Get fresh book
        book = self.exchange.order_book(symbol, depth=1)
        if not book.bids or not book.asks:
            logger.warning("[mm] Empty order book")
            await asyncio.sleep(self._refresh_sec)
            return

        best_bid = Decimal(str(book.bids[0][0]))
        best_ask = Decimal(str(book.asks[0][0]))
        mid = (best_bid + best_ask) / Decimal("2")

        spread_pct = float(best_bid - best_ask) / float(mid) * 100
        our_spread = float(self._spread)

        # Place bid slightly below best bid (or at a desirable level)
        bid_price = mid * (Decimal("1") - self._spread / Decimal("200"))
        ask_price = mid * (Decimal("1") + self._spread / Decimal("200"))

        bid_price = bid_price.quantize(Decimal("0.1"), ROUND_DOWN)
        ask_price = ask_price.quantize(Decimal("0.1"), ROUND_DOWN)

        # Don't cross the spread
        if bid_price >= best_ask:
            bid_price = best_ask - Decimal("0.1")
        if ask_price <= best_bid:
            ask_price = best_bid + Decimal("0.1")

        try:
            r = self.exchange.place_order(
                symbol=symbol,
                side="BUY",
                order_type="LIMIT",
                quantity=str(self._qty),
                price=str(bid_price),
            )
            self._bid_id = r.get("orderId")
        except Exception as e:
            logger.error(f"[mm] Bid failed: {e}")

        try:
            r = self.exchange.place_order(
                symbol=symbol,
                side="SELL",
                order_type="LIMIT",
                quantity=str(self._qty),
                price=str(ask_price),
            )
            self._ask_id = r.get("orderId")
        except Exception as e:
            logger.error(f"[mm] Ask failed: {e}")

        logger.debug(
            f"[mm] Bid {bid_price} | Ask {ask_price} | Mid {mid:.1f} | "
            f"Spread {abs(spread_pct):.4f}% | OurSpread {our_spread:.2f}%"
        )

        await asyncio.sleep(self._refresh_sec)
