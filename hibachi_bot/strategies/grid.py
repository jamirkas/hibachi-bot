"""
Grid trading strategy with take-profit and stop-loss.

Features:
- Configurable grid levels, step %, order size
- Per-grid TP/SL
- Trailing take-profit (optional)
- PnL tracking
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN

from .base import BaseStrategy
from ..exchange import HibachiExchange
from ..config import GridConfig, RiskConfig

logger = logging.getLogger("hibachi.strategy.grid")


@dataclass
class GridLevel:
    side: str           # "BUY" | "SELL"
    price: Decimal
    order_id: int | None = None
    entry_price: Decimal | None = None  # Actual fill price
    filled: bool = False
    filled_at: float = 0.0              # Timestamp
    pnl: float = 0.0


class GridStrategy(BaseStrategy):
    """
    Grid trading bot.

    Places N buy levels below mid-price and N sell levels above.
    When a buy fills, tracks it for TP/SL. When a sell fills, same.
    """

    def __init__(self, exchange: HibachiExchange, config: GridConfig, risk: RiskConfig):
        super().__init__(exchange, config, risk)
        self._cfg = config
        self._levels: list[GridLevel] = []
        self._pnl_total: float = 0.0
        self._rounds: int = 0

    async def setup(self) -> None:
        symbol = self._cfg.symbol
        logger.info(f"🧱 Grid: {self._cfg.grid_count}×2 levels, "
                     f"step={self._cfg.step_pct}%, size=${self._cfg.order_size_usdt}, "
                     f"TP={self._cfg.take_profit_pct}%, SL={self._cfg.stop_loss_pct}%")

        self.exchange.cancel_all_orders(symbol)
        self._levels.clear()

        await self._place_grid()

    async def tick(self) -> None:
        symbol = self._cfg.symbol

        # 1. Check existing orders — what filled?
        open_orders = self.exchange.open_orders(symbol)
        open_ids = {o["orderId"] for o in open_orders}

        for level in self._levels:
            if level.order_id and level.order_id not in open_ids and not level.filled:
                level.filled = True
                level.filled_at = time.time()
                logger.info(f"  ✅ Grid fill: {level.side} @ {level.price}")

        # 2. Check TP/SL on filled levels
        book = self.exchange.order_book(symbol, depth=1)
        if book.bids and book.asks:
            mark = Decimal(str((book.bids[0][0] + book.asks[0][0]) / 2))
            await self._check_exits(mark)

        # 3. If all filled, reset grid
        all_filled = all(lv.filled for lv in self._levels if lv.order_id)
        if all_filled and len(self._levels) > 0:
            self._rounds += 1
            logger.info(f"🔄 Grid round {self._rounds} complete! Total PnL: ${self._pnl_total:.2f}")
            self._levels.clear()
            await self._place_grid()

        # 4. Replace filled levels on opposite side
        await self._replace_filled()

        await asyncio.sleep(self._cfg.refresh_sec)

    def _price_precision(self, price: Decimal) -> Decimal:
        """Round to reasonable precision for the exchange."""
        return price.quantize(Decimal("0.1"), ROUND_DOWN)

    async def _place_grid(self) -> None:
        """Place initial buy and sell ladders."""
        symbol = self._cfg.symbol
        book = self.exchange.order_book(symbol, depth=1)
        if not book.bids or not book.asks:
            logger.warning("Empty order book — cannot place grid")
            return

        mid = Decimal(str((book.bids[0][0] + book.asks[0][0]) / 2))
        step = self._price_precision(mid * Decimal(str(self._cfg.step_pct)) / Decimal("100"))
        qty = self._price_precision(Decimal(str(self._cfg.order_size_usdt)) / mid)

        for i in range(self._cfg.grid_count):
            buy_price = self._price_precision(mid - step * (i + 1))
            sell_price = self._price_precision(mid + step * (i + 1))

            if buy_price > 0:
                self._place_order("BUY", buy_price, qty, symbol)
            self._place_order("SELL", sell_price, qty, symbol)

    def _place_order(self, side: str, price: Decimal, qty: Decimal, symbol: str) -> None:
        try:
            resp = self.exchange.place_order(
                symbol=symbol,
                side=side,
                order_type="LIMIT",
                quantity=str(qty),
                price=str(price),
                time_in_force="GTC",
            )
            oid = resp.get("orderId")
            self._levels.append(GridLevel(side=side, price=price, order_id=oid))
        except Exception as e:
            logger.error(f"Order failed ({side} @ {price}): {e}")

    async def _check_exits(self, mark: Decimal) -> None:
        """Close positions at TP or SL."""
        for lv in self._levels:
            if not lv.filled or lv.order_id is not None:
                continue

            pnl_pct = float((mark - lv.price) / lv.price * 100)
            if lv.side == "SELL":
                pnl_pct = -pnl_pct

            # Take profit
            if pnl_pct >= self._cfg.take_profit_pct:
                self._close_grid_level(lv, mark, "TP", pnl_pct)
            # Stop loss
            elif pnl_pct <= -self._cfg.stop_loss_pct:
                self._close_grid_level(lv, mark, "SL", pnl_pct)

    def _close_grid_level(self, lv: GridLevel, mark: Decimal, reason: str, pnl_pct: float) -> None:
        """Market-close a filled grid level."""
        symbol = self._cfg.symbol
        close_side = "SELL" if lv.side == "BUY" else "BUY"
        qty = self._price_precision(Decimal(str(self._cfg.order_size_usdt)) / mark)
        pnl_usdt = self._cfg.order_size_usdt * pnl_pct / 100

        try:
            self.exchange.place_order(
                symbol=symbol,
                side=close_side,
                order_type="MARKET",
                quantity=str(qty),
                reduce_only=True,
            )
            self._pnl_total += pnl_usdt
            lv.order_id = None  # Mark as closed
            logger.info(f"  [{reason}] {lv.side} @ {lv.price} → {mark} | "
                         f"{pnl_pct:+.2f}% | ${pnl_usdt:+.2f} | Total: ${self._pnl_total:+.2f}")
        except Exception as e:
            logger.error(f"Close failed: {e}")

    async def _replace_filled(self) -> None:
        """Replace filled grid levels on the opposite side."""
        symbol = self._cfg.symbol
        book = self.exchange.order_book(symbol, depth=1)
        if not book.bids or not book.asks:
            return
        mid = Decimal(str((book.bids[0][0] + book.asks[0][0]) / 2))
        step = self._price_precision(mid * Decimal(str(self._cfg.step_pct)) / Decimal("100"))
        qty = self._price_precision(Decimal(str(self._cfg.order_size_usdt)) / mid)

        for lv in self._levels:
            if not lv.filled or lv.order_id is not None:
                continue

            if lv.side == "BUY":
                new_price = self._price_precision(lv.price + step * 2)
                if new_price > mid:
                    self._place_order("SELL", new_price, qty, symbol)
            else:
                new_price = self._price_precision(lv.price - step * 2)
                if new_price < mid and new_price > 0:
                    self._place_order("BUY", new_price, qty, symbol)
