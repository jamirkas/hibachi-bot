"""
Market making strategy with adaptive spread and multi-level Close Mode.

Features:
- Configurable spread width, order count, size
- Position limits (long/short exposure caps)
- Auto-cancel on sharp price moves
- Adaptive spread: widen when volatile, tighten when calm
- Multi-level Close Mode (from zo-market-maker-ts):
  🟡 YELLOW (exposure > 50% threshold): reduce order size by half
  🟠 RED (exposure > 100% threshold): only reducing side, tight spread
  🔴 CRITICAL (exposure > 200% threshold): pause MM, market-close-only

Inspired by: https://github.com/yat1ma30/zo-market-maker-ts
"""

import asyncio
import logging
import time
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Optional

from .base import BaseStrategy
from ..exchange import HibachiExchange
from ..config import MMConfig, RiskConfig

logger = logging.getLogger("hibachi.strategy.mm")


class CloseLevel(Enum):
    """Close Mode severity levels."""
    NORMAL = "normal"       # Full MM both sides
    YELLOW = "yellow"       # Reduce order size 50%
    RED = "red"             # Only reducing side, tight spread
    CRITICAL = "critical"   # Pause MM, only market-close


class MarketMakingStrategy(BaseStrategy):
    """
    Market maker — maintains bid/ask orders around mid-price.

    With Hibachi's 0% maker fee, every round-trip is pure spread profit.

    Close Mode Levels:
      🟡 YELLOW  (exposure > 50% threshold): half-size orders
      🟠 RED     (exposure > 100% threshold): reducing side only
      🔴 CRITICAL (exposure > 200% threshold): pause all, close-only
    """

    def __init__(self, exchange: HibachiExchange, config: MMConfig, risk: RiskConfig):
        super().__init__(exchange, config, risk)
        self._cfg = config
        self._active_bids: list[int] = []
        self._active_asks: list[int] = []
        self._last_mid: Optional[Decimal] = None
        self._long_exposure: float = 0.0
        self._short_exposure: float = 0.0
        self._pnl_total: float = 0.0
        self._last_volatility: float = 0.0
        self._close_level: CloseLevel = CloseLevel.NORMAL
        self._close_notified: set[CloseLevel] = set()

    async def setup(self) -> None:
        symbol = self._cfg.symbol
        cm = "ON" if self._cfg.close_mode_enabled else "OFF"
        logger.info(
            f"📊 MM: spread={self._cfg.spread_pct}%, "
            f"order=${self._cfg.order_size_usdt}, "
            f"maxLong=${self._cfg.max_long_usdt}, maxShort=${self._cfg.max_short_usdt}, "
            f"closeMode={cm} (threshold=${self._cfg.close_mode_threshold_usd})"
        )

        self.exchange.cancel_all_orders(symbol)
        self._update_exposure()

    def _determine_close_level(self) -> CloseLevel:
        """Determine Close Mode level based on current exposure."""
        if not self._cfg.close_mode_enabled:
            return CloseLevel.NORMAL

        threshold = self._cfg.close_mode_threshold_usd
        max_exposure = max(self._long_exposure, self._short_exposure)

        if max_exposure > threshold * 2:
            return CloseLevel.CRITICAL
        elif max_exposure > threshold:
            return CloseLevel.RED
        elif max_exposure > threshold * 0.5:
            return CloseLevel.YELLOW
        return CloseLevel.NORMAL

    async def tick(self) -> None:
        symbol = self._cfg.symbol

        # Cancel all current orders
        for oid in self._active_bids + self._active_asks:
            try:
                self.exchange.cancel_order(oid)
            except Exception:
                pass
        self._active_bids.clear()
        self._active_asks.clear()

        # Get fresh book
        book = self.exchange.order_book(symbol, depth=5)
        if not book.bids or not book.asks:
            await asyncio.sleep(self._cfg.refresh_sec)
            return

        best_bid = Decimal(str(book.bids[0][0]))
        best_ask = Decimal(str(book.asks[0][0]))
        mid = (best_bid + best_ask) / Decimal("2")

        # Adaptive spread: widen if price is moving fast
        spread_pct = self._cfg.spread_pct
        if self._cfg.adaptive_spread and self._last_mid:
            price_move_pct = abs(float((mid - self._last_mid) / self._last_mid * 100))
            self._last_volatility = price_move_pct
            if price_move_pct > 0.1:
                spread_pct = min(
                    spread_pct * (1 + price_move_pct * 10),
                    self._cfg.max_spread_pct,
                )
            spread_pct = max(spread_pct, self._cfg.min_spread_pct)

        self._last_mid = mid

        # Cancel all if price moved too fast
        if (
            self._cfg.cancel_on_price_move_pct
            and self._last_volatility > self._cfg.cancel_on_price_move_pct
        ):
            logger.warning(
                f"⚠️ Price moved {self._last_volatility:.2f}% — pausing MM"
            )
            await asyncio.sleep(self._cfg.refresh_sec * 2)
            return

        # Update exposure from positions
        self._update_exposure()

        # ── Close Mode: determine level ──
        level = self._determine_close_level()

        # Log transitions
        if level != self._close_level:
            prev = self._close_level
            self._close_level = level
            if level != CloseLevel.NORMAL:
                icon = {"YELLOW": "🟡", "RED": "🟠", "CRITICAL": "🔴"}[level.name]
                logger.warning(
                    f"{icon} Close Mode: {prev.name} → {level.name} "
                    f"(Long=${self._long_exposure:.0f}, Short=${self._short_exposure:.0f}, "
                    f"Threshold=${self._cfg.close_mode_threshold_usd:.0f})"
                )
            else:
                logger.info(
                    f"🟢 Close Mode: {prev.name} → NORMAL — full MM resumed"
                )

        # ── Apply Close Mode ──
        if level == CloseLevel.CRITICAL:
            # Pause MM entirely — don't place any new orders
            logger.error(
                f"🔴 CRITICAL: Exposure critical (Long=${self._long_exposure:.0f}, "
                f"Short=${self._short_exposure:.0f}) — pausing MM"
            )
            await asyncio.sleep(self._cfg.refresh_sec * 3)
            return

        place_bids = True
        place_asks = True
        effective_spread = spread_pct
        size_multiplier = 1.0

        if level == CloseLevel.YELLOW:
            # Half-size orders to slow down exposure buildup
            size_multiplier = 0.5
            # Slightly wider spread to reduce fill rate
            effective_spread = max(spread_pct * 1.2, self._cfg.max_spread_pct)

        elif level == CloseLevel.RED:
            # Only the reducing side
            if self._long_exposure > self._short_exposure:
                place_bids = False  # Don't buy more
            else:
                place_asks = False  # Don't sell more
            effective_spread = self._cfg.close_mode_tight_spread
            # Normal size — we want to unwind fast

        # Place bid/ask ladder
        qty = Decimal(str(self._cfg.order_size_usdt)) / mid
        qty = (qty * Decimal(str(size_multiplier))).quantize(
            Decimal("0.0001"), ROUND_DOWN
        )

        half_spread = Decimal(str(effective_spread)) / Decimal("200")

        for i in range(self._cfg.max_orders_per_side):
            # Bids (buy) below mid
            if place_bids and self._long_exposure < self._cfg.max_long_usdt:
                bid_price = mid * (Decimal("1") - half_spread * (i + 1))
                bid_price = bid_price.quantize(Decimal("0.1"), ROUND_DOWN)
                if bid_price < best_ask:
                    oid = self._place("BUY", bid_price, qty, symbol)
                    if oid:
                        self._active_bids.append(oid)

            # Asks (sell) above mid
            if place_asks and self._short_exposure < self._cfg.max_short_usdt:
                ask_price = mid * (Decimal("1") + half_spread * (i + 1))
                ask_price = ask_price.quantize(Decimal("0.1"), ROUND_DOWN)
                if ask_price > best_bid:
                    oid = self._place("SELL", ask_price, qty, symbol)
                    if oid:
                        self._active_asks.append(oid)

        spread_bps = float(best_ask - best_bid) / float(mid) * 10000
        level_tag = {
            CloseLevel.NORMAL: "",
            CloseLevel.YELLOW: " 🟡YELLOW",
            CloseLevel.RED: " 🟠RED",
        }.get(level, "")
        logger.debug(
            f"📊 Mid={mid:.1f}  Spread={spread_bps:.1f}bps  "
            f"OurSpread={effective_spread:.3f}%{level_tag}  "
            f"Size={size_multiplier:.0%}  "
            f"Long=${self._long_exposure:.0f}  Short=${self._short_exposure:.0f}  "
            f"Vol={self._last_volatility:.3f}%"
        )

        await asyncio.sleep(self._cfg.refresh_sec)

    def _place(
        self, side: str, price: Decimal, qty: Decimal, symbol: str
    ) -> int | None:
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
        """Read current positions to track exposure."""
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
