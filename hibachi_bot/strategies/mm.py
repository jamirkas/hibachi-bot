"""
Market making strategy with accumulate-then-reduce logic.

- Accumulates up to configured notional limit
- After limit: only reducing orders in profit (vs entry)
- Stop-loss on unrealized → aggressive close + pause
- Order refresh ~every 40s
"""

import asyncio
import logging
import time
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from .base import BaseStrategy
from ..exchange import HibachiExchange
from ..config import MMConfig, RiskConfig

logger = logging.getLogger("hibachi.strategy.mm")


class MarketMakingStrategy(BaseStrategy):
    def __init__(self, exchange: HibachiExchange, config: MMConfig, risk: RiskConfig):
        super().__init__(exchange, config, risk)
        self._cfg = config
        self._active_bids: list = []
        self._active_asks: list = []
        self._last_mid: Optional[Decimal] = None
        self._long_exposure: float = 0.0
        self._short_exposure: float = 0.0
        self._last_refresh_ts: float = 0.0

    async def setup(self) -> None:
        symbol = self._cfg.symbol
        logger.info(
            f"MM: spread={self._cfg.spread_pct}%, "
            f"order=${self._cfg.order_size_usdt}, "
            f"maxLong=${self._cfg.max_long_usdt}, maxShort=${self._cfg.max_short_usdt}"
        )
        try:
            self.exchange.cancel_all_orders(symbol)
        except Exception as e:
            logger.warning(f"setup cancel_all: {e}")
        self._update_exposure()

    async def tick(self) -> None:
        symbol = self._cfg.symbol
        now = time.time()

        book = self.exchange.order_book(symbol, depth=5)
        if not book.bids or not book.asks:
            await asyncio.sleep(2)
            return

        best_bid = Decimal(str(book.bids[0][0]))
        best_ask = Decimal(str(book.asks[0][0]))
        mid = (best_bid + best_ask) / Decimal("2")

        should_refresh = (now - self._last_refresh_ts > 40) or (not self._active_bids and not self._active_asks)
        if not should_refresh:
            await asyncio.sleep(5)
            return

        try:
            self.exchange.cancel_all_orders(symbol)
        except Exception as e:
            logger.warning(f"cancel_all: {e}")
        await asyncio.sleep(1.0)

        self._active_bids.clear()
        self._active_asks.clear()
        self._last_refresh_ts = now
        self._update_exposure()

        entry = None
        pos_size = 0.0
        unrealized = 0.0
        try:
            for p in self.exchange.positions():
                sz = float(p.get("size", p.get("quantity", 0)))
                if abs(sz) > 0.00001:
                    pos_size = sz
                    entry = Decimal(str(p.get("entryPrice", p.get("avgEntryPrice", mid))))
                    unrealized = float(p.get("unrealizedPnl", p.get("pnl", 0)))
                    break
        except Exception:
            pass

        current_exposure = abs(pos_size) * float(mid)
        STOP_LOSS_USD = 25.0

        if unrealized < -STOP_LOSS_USD and abs(pos_size) > 0.00001:
            logger.warning(f"STOP LOSS: PnL=${unrealized:.2f}, closing")
            close_side = "ASK" if pos_size > 0 else "BID"
            close_qty = Decimal(str(abs(pos_size))).quantize(Decimal("0.0001"), ROUND_DOWN)
            close_price = best_bid if pos_size > 0 else best_ask
            self._place(close_side, close_price, close_qty, symbol)
            self._last_refresh_ts = now + 600
            await asyncio.sleep(10)
            return

        qty = (Decimal(str(self._cfg.order_size_usdt)) / mid).quantize(Decimal("0.0001"), ROUND_DOWN)
        offsets = [Decimal("0.00035"), Decimal("0.00055"), Decimal("0.00075"), Decimal("0.00095"), Decimal("0.00115")]

        ACCUMULATE_LIMIT = 2000.0

        place_bids = True
        place_asks = True
        min_profit = Decimal("0.0008")

        if current_exposure >= ACCUMULATE_LIMIT and entry:
            if pos_size > 0:
                place_bids = False
                logger.info(f"LONG full ({current_exposure:.0f}$), reduce only, entry={entry:.1f}")
            else:
                place_asks = False
                logger.info(f"SHORT full ({current_exposure:.0f}$), reduce only, entry={entry:.1f}")

        for off in offsets:
            if place_bids and self._long_exposure < self._cfg.max_long_usdt:
                bp = (mid * (Decimal("1") - off)).quantize(Decimal("0.1"), ROUND_DOWN)
                if entry and pos_size < 0 and current_exposure >= ACCUMULATE_LIMIT:
                    max_buy = (entry * (Decimal("1") - min_profit)).quantize(Decimal("0.1"), ROUND_DOWN)
                    if bp > max_buy:
                        bp = max_buy
                if bp < best_ask:
                    oid = self._place("BID", bp, qty, symbol)
                    if oid:
                        self._active_bids.append(oid)

            if place_asks and self._short_exposure < self._cfg.max_short_usdt:
                ap = (mid * (Decimal("1") + off)).quantize(Decimal("0.1"), ROUND_DOWN)
                if entry and pos_size > 0 and current_exposure >= ACCUMULATE_LIMIT:
                    min_sell = (entry * (Decimal("1") + min_profit)).quantize(Decimal("0.1"), ROUND_DOWN)
                    if ap < min_sell:
                        ap = min_sell
                if ap > best_bid:
                    oid = self._place("ASK", ap, qty, symbol)
                    if oid:
                        self._active_asks.append(oid)

        logger.info(f"Refresh mid={mid:.1f} pos={pos_size:.4f} exp=${current_exposure:.0f} L=${self._long_exposure:.0f} S=${self._short_exposure:.0f}")
        await asyncio.sleep(6)

    def _place(self, side: str, price: Decimal, qty: Decimal, symbol: str):
        try:
            resp = self.exchange.place_order(
                symbol=symbol,
                side=side,
                order_type="LIMIT",
                quantity=str(qty),
                price=str(price),
                time_in_force="GTC",
            )
            return resp.get("orderId")
        except Exception as e:
            logger.error(f"MM order failed: {e}")
            return None

    def _update_exposure(self) -> None:
        try:
            positions = self.exchange.positions()
            self._long_exposure = 0.0
            self._short_exposure = 0.0
            for p in positions:
                size = float(p.get("size", p.get("quantity", 0)))
                mark = float(p.get("markPrice", 0))
                if size > 0:
                    self._long_exposure += abs(size) * mark
                elif size < 0:
                    self._short_exposure += abs(size) * mark
        except Exception:
            pass
