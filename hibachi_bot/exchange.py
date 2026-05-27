"""
Hibachi Exchange REST API wrapper with resilience.

Features:
- Exponential backoff with jitter on transient failures
- Circuit breaker: 3 consecutive failures → pause for 30s
- Specific error handling for 429 (rate limit), 503 (maintenance), 5xx
"""

import requests
import json
import time
import random
import logging
from dataclasses import dataclass
from typing import Optional

from .auth import HibachiAuth

logger = logging.getLogger("hibachi")


@dataclass
class OrderBook:
    bids: list[tuple[float, float]]  # (price, size)
    asks: list[tuple[float, float]]
    timestamp: int


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open — all requests blocked."""
    pass


class HibachiExchange:
    """REST API client for Hibachi with retry logic and circuit breaker."""

    REST_URL = "https://api.hibachi.xyz"
    DATA_URL = "https://data-api.hibachi.xyz"

    # Backoff config
    MAX_RETRIES = 3
    BASE_DELAY = 1.0  # seconds
    MAX_DELAY = 30.0

    # Circuit breaker config
    CB_FAILURE_THRESHOLD = 3       # consecutive failures to open
    CB_TIMEOUT = 30                # seconds to stay open
    CB_HALF_OPEN_ALLOW = 1         # allow 1 request in half-open state

    def __init__(self, api_key: str, secret_key: str, account_id: int):
        self.auth = HibachiAuth(api_key, secret_key)
        self.account_id = account_id
        self.session = requests.Session()

        # Circuit breaker state
        self._cb_failures: int = 0
        self._cb_last_failure: float = 0.0
        self._cb_open: bool = False
        self._cb_half_open_used: int = 0

    # ── Circuit Breaker ──────────────────────────────

    def _cb_check(self):
        """Check circuit breaker before request. Raises CircuitBreakerOpen if blocked."""
        if not self._cb_open:
            return

        elapsed = time.time() - self._cb_last_failure
        if elapsed > self.CB_TIMEOUT:
            # Transition to half-open
            self._cb_open = False
            self._cb_half_open_used = 0
            logger.info("🔌 Circuit breaker: half-open — allowing test request")
        else:
            remaining = int(self.CB_TIMEOUT - elapsed)
            raise CircuitBreakerOpen(
                f"Circuit breaker open for {remaining}s "
                f"(after {self._cb_failures} consecutive failures)"
            )

    def _cb_success(self):
        """Report successful request to circuit breaker."""
        if not self._cb_open and self._cb_half_open_used > 0:
            logger.info("🔌 Circuit breaker: closed — half-open test passed")
        self._cb_failures = 0
        self._cb_half_open_used = 0

    def _cb_failure(self):
        """Report failed request to circuit breaker."""
        self._cb_failures += 1
        self._cb_last_failure = time.time()
        if self._cb_failures >= self.CB_FAILURE_THRESHOLD and not self._cb_open:
            self._cb_open = True
            logger.error(
                f"🔌 Circuit breaker: OPEN ({self._cb_failures} consecutive failures, "
                f"blocking for {self.CB_TIMEOUT}s)"
            )

    # ── Retry helpers ────────────────────────────────

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter."""
        delay = min(self.BASE_DELAY * (2 ** attempt), self.MAX_DELAY)
        jitter = random.uniform(0, delay * 0.5)
        return delay + jitter

    def _should_retry(self, response, attempt: int) -> bool:
        """Decide whether to retry based on status code and attempt count."""
        if attempt >= self.MAX_RETRIES:
            return False
        # Retry on rate limit, server errors, and connection issues
        return response.status_code in (429, 500, 502, 503, 504)

    # ── Core request ─────────────────────────────────

    def _req(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        base_url: str | None = None,
    ) -> dict:
        """Make an authenticated request with retry + circuit breaker."""
        url = f"{base_url or self.REST_URL}{path}"
        retryable_response = None

        for attempt in range(self.MAX_RETRIES + 1):
            # Check circuit breaker
            try:
                self._cb_check()
            except CircuitBreakerOpen:
                raise

            try:
                headers = self.auth.sign(method, path, body)
                resp = self.session.request(
                    method, url, json=body, headers=headers, timeout=10
                )

                # Success
                if resp.status_code < 400:
                    self._cb_success()
                    return resp.json()

                # Rate limited
                if resp.status_code == 429:
                    logger.warning(
                        f"⚠️  Rate limited (429) on {method} {path}, "
                        f"attempt {attempt + 1}/{self.MAX_RETRIES + 1}"
                    )
                    if self._should_retry(resp, attempt):
                        delay = self._backoff_delay(attempt)
                        time.sleep(delay)
                        retryable_response = resp
                        continue
                    resp.raise_for_status()

                # Server error
                if resp.status_code >= 500:
                    logger.warning(
                        f"⚠️  Server error ({resp.status_code}) on {method} {path}, "
                        f"attempt {attempt + 1}/{self.MAX_RETRIES + 1}"
                    )
                    if self._should_retry(resp, attempt):
                        delay = self._backoff_delay(attempt)
                        time.sleep(delay)
                        retryable_response = resp
                        continue
                    resp.raise_for_status()

                # Other errors
                logger.error(
                    f"❌ HTTP {resp.status_code} on {method} {path}: "
                    f"{resp.text[:200]}"
                )
                resp.raise_for_status()

            except (requests.ConnectionError, requests.Timeout) as e:
                logger.warning(
                    f"⚠️  Connection error on {method} {path}: {e}, "
                    f"attempt {attempt + 1}/{self.MAX_RETRIES + 1}"
                )
                if attempt < self.MAX_RETRIES:
                    delay = self._backoff_delay(attempt)
                    time.sleep(delay)
                    continue
                self._cb_failure()
                raise

            except requests.HTTPError:
                self._cb_failure()
                raise

            except Exception:
                self._cb_failure()
                raise

        # All retries exhausted
        self._cb_failure()
        logger.error(f"❌ All {self.MAX_RETRIES + 1} attempts failed for {method} {path}")
        if retryable_response is not None:
            retryable_response.raise_for_status()
        raise RuntimeError(f"Request failed: {method} {path}")

    def _get_data(self, path: str) -> dict:
        """Public data endpoint (no auth, no retry for simplicity)."""
        return self.session.get(
            f"{self.DATA_URL}{path}", timeout=10
        ).json()

    # ── Account ──────────────────────────────────────

    def balance(self) -> dict:
        return self._req("GET", f"/capital/balance?accountId={self.account_id}")

    def account_info(self) -> dict:
        return self._req("GET", f"/trade/account/info?accountId={self.account_id}")

    # ── Orders ───────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,  # "BUY" | "SELL"
        order_type: str,  # "LIMIT" | "MARKET"
        quantity: str,
        price: str | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
    ) -> dict:
        body = {
            "accountId": self.account_id,
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": str(quantity),
            "timeInForce": time_in_force,
            "reduceOnly": reduce_only,
        }
        if price is not None:
            body["price"] = str(price)
        return self._req("POST", "/trade/order", body)

    def cancel_order(self, order_id: int) -> dict:
        return self._req(
            "DELETE",
            f"/trade/order?orderId={order_id}&accountId={self.account_id}",
        )

    def cancel_all_orders(self, symbol: str | None = None) -> dict:
        path = f"/trade/orders?accountId={self.account_id}"
        if symbol:
            path += f"&symbol={symbol}"
        return self._req("DELETE", path)

    def open_orders(self, symbol: str | None = None) -> list[dict]:
        path = f"/trade/orders?accountId={self.account_id}"
        if symbol:
            path += f"&symbol={symbol}"
        return self._req("GET", path)

    def positions(self) -> list[dict]:
        info = self.account_info()
        return info.get("positions", [])

    # ── Market Data ──────────────────────────────────

    def order_book(self, symbol: str, depth: int = 10, granularity: float = 0.01) -> OrderBook:
        data = self._get_data(
            f"/market/data/orderbook?symbol={symbol}&depth={depth}&granularity={granularity}"
        )
        bids = [(float(b["price"]), float(b["size"])) for b in data.get("bids", [])]
        asks = [(float(a["price"]), float(a["size"])) for a in data.get("asks", [])]
        return OrderBook(bids=bids, asks=asks, timestamp=data.get("timestamp", 0))

    def ticker_price(self, symbol: str) -> float:
        data = self._get_data(f"/market/data/prices?symbol={symbol}")
        return float(data.get("price", data.get("lastPrice", 0)))

    def exchange_info(self) -> dict:
        return self._get_data("/market/exchange-info")
