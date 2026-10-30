"""
Hibachi Exchange REST API wrapper with resilience.

Features:
- Exponential backoff with jitter on transient failures
- Circuit breaker: 3 consecutive failures → pause for 30s
- Order signing via eth_account.unsafe_sign_hash
- Correct orderbook parsing (bid.levels / ask.levels)
"""

import hashlib
import requests
import json
import time
import random
import logging
from dataclasses import dataclass
from typing import Optional

from eth_account import Account
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

    MAX_RETRIES = 3
    BASE_DELAY = 1.0
    MAX_DELAY = 30.0

    CB_FAILURE_THRESHOLD = 3
    CB_TIMEOUT = 30
    CB_HALF_OPEN_ALLOW = 1

    def __init__(self, api_key: str, secret_key: str, account_id: int):
        self.auth = HibachiAuth(api_key, secret_key)
        self.account_id = account_id
        self.session = requests.Session()

        self._cb_failures: int = 0
        self._cb_last_failure: float = 0.0
        self._cb_open: bool = False
        self._cb_half_open_used: int = 0

    def _cb_check(self):
        if not self._cb_open:
            return
        elapsed = time.time() - self._cb_last_failure
        if elapsed > self.CB_TIMEOUT:
            self._cb_open = False
            self._cb_half_open_used = 0
            logger.info("Circuit breaker: half-open")
        else:
            remaining = int(self.CB_TIMEOUT - elapsed)
            raise CircuitBreakerOpen(
                f"Circuit breaker open for {remaining}s "
                f"(after {self._cb_failures} consecutive failures)"
            )

    def _cb_success(self):
        if not self._cb_open and self._cb_half_open_used > 0:
            logger.info("Circuit breaker: closed")
        self._cb_failures = 0
        self._cb_half_open_used = 0

    def _cb_failure(self):
        self._cb_failures += 1
        self._cb_last_failure = time.time()
        if self._cb_failures >= self.CB_FAILURE_THRESHOLD and not self._cb_open:
            self._cb_open = True
            logger.error(
                f"Circuit breaker: OPEN ({self._cb_failures} consecutive failures, "
                f"blocking for {self.CB_TIMEOUT}s)"
            )

    def _backoff_delay(self, attempt: int) -> float:
        delay = min(self.BASE_DELAY * (2 ** attempt), self.MAX_DELAY)
        jitter = random.uniform(0, delay * 0.5)
        return delay + jitter

    def _should_retry(self, response, attempt: int) -> bool:
        if attempt >= self.MAX_RETRIES:
            return False
        return response.status_code in (429, 500, 502, 503, 504)

    def _sign_payload(self, payload: bytes) -> str:
        """Sign arbitrary bytes with the account private key."""
        digest = hashlib.sha256(payload).digest()
        pk = self.auth.secret_key
        if isinstance(pk, bytes):
            pk = pk.decode()
        if pk.startswith("0x"):
            pk = pk[2:]
        signed = Account.unsafe_sign_hash(digest, private_key=bytes.fromhex(pk))
        return signed.signature.hex()

    def _req(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        base_url: str | None = None,
    ) -> dict:
        url = f"{base_url or self.REST_URL}{path}"
        retryable_response = None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                self._cb_check()
            except CircuitBreakerOpen:
                raise

            try:
                headers = self.auth.sign(method, path, body)
                resp = self.session.request(
                    method, url, json=body, headers=headers, timeout=10
                )

                if resp.status_code < 400:
                    self._cb_success()
                    return resp.json()

                if resp.status_code == 429:
                    logger.warning(f"Rate limited on {method} {path}")
                    if self._should_retry(resp, attempt):
                        time.sleep(self._backoff_delay(attempt))
                        retryable_response = resp
                        continue
                    resp.raise_for_status()

                if resp.status_code >= 500:
                    logger.warning(f"Server error {resp.status_code} on {method} {path}")
                    if self._should_retry(resp, attempt):
                        time.sleep(self._backoff_delay(attempt))
                        retryable_response = resp
                        continue
                    resp.raise_for_status()

                logger.error(f"HTTP {resp.status_code} on {method} {path}: {resp.text[:200]}")
                resp.raise_for_status()

            except (requests.ConnectionError, requests.Timeout) as e:
                logger.warning(f"Connection error on {method} {path}: {e}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(self._backoff_delay(attempt))
                    continue
                self._cb_failure()
                raise

            except requests.HTTPError:
                self._cb_failure()
                raise

            except Exception:
                self._cb_failure()
                raise

        self._cb_failure()
        logger.error(f"All attempts failed for {method} {path}")
        if retryable_response is not None:
            retryable_response.raise_for_status()
        raise RuntimeError(f"Request failed: {method} {path}")

    def _get_data(self, path: str) -> dict:
        return self.session.get(f"{self.DATA_URL}{path}", timeout=10).json()

    def balance(self) -> dict:
        return self._req("GET", f"/capital/balance?accountId={self.account_id}")

    def account_info(self) -> dict:
        return self._req("GET", f"/trade/account/info?accountId={self.account_id}")

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: str,
        price: str | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
    ) -> dict:
        import struct
        nonce = int(time.time() * 1000)
        # Map side
        side_flag = 1 if side.upper() in ("ASK", "SELL") else 0
        qty_int = int(float(quantity) * 1e8)
        price_int = int(float(price) * 1e8) if price else 0
        max_fees = 5000  # 0.05% in bps-ish, adjust if needed

        payload = struct.pack(">Q I Q I Q Q", nonce, 0, qty_int, side_flag, price_int, max_fees)
        signature = self._sign_payload(payload)

        body = {
            "accountId": self.account_id,
            "symbol": symbol,
            "side": "ASK" if side.upper() in ("ASK", "SELL") else "BID",
            "type": order_type.upper(),
            "quantity": str(quantity),
            "timeInForce": time_in_force,
            "reduceOnly": reduce_only,
            "nonce": nonce,
            "signature": signature,
            "maxFeesPercent": "0.0005",
        }
        if price is not None:
            body["price"] = str(price)
        return self._req("POST", "/trade/order", body)

    def cancel_order(self, order_id: str) -> dict:
        oid = int(order_id)
        payload = oid.to_bytes(8, byteorder="big")
        signature = self._sign_payload(payload)
        body = {
            "accountId": self.account_id,
            "orderId": order_id,
            "signature": signature,
        }
        return self._req("DELETE", "/trade/order", body)

    def cancel_all_orders(self, symbol: str | None = None) -> dict:
        import struct
        nonce = int(time.time() * 1000)
        payload = struct.pack(">Q", nonce)
        signature = self._sign_payload(payload)
        body = {
            "accountId": self.account_id,
            "nonce": nonce,
            "signature": signature,
        }
        if symbol:
            body["symbol"] = symbol
        return self._req("DELETE", "/trade/orders", body)

    def open_orders(self, symbol: str | None = None) -> list[dict]:
        path = f"/trade/orders?accountId={self.account_id}"
        if symbol:
            path += f"&symbol={symbol}"
        return self._req("GET", path)

    def positions(self) -> list[dict]:
        info = self.account_info()
        return info.get("positions", [])

    def order_book(self, symbol: str, depth: int = 10, granularity: float = 1) -> OrderBook:
        data = self._get_data(
            f"/market/data/orderbook?symbol={symbol}&depth={depth}&granularity={granularity}"
        )
        bid_levels = data.get("bid", {}).get("levels", [])
        ask_levels = data.get("ask", {}).get("levels", [])
        bids = [(float(b["price"]), float(b["quantity"])) for b in bid_levels]
        asks = [(float(a["price"]), float(a["quantity"])) for a in ask_levels]
        return OrderBook(bids=bids, asks=asks, timestamp=0)

    def ticker_price(self, symbol: str) -> float:
        data = self._get_data(f"/market/data/prices?symbol={symbol}")
        return float(data.get("markPrice", data.get("bidPrice", data.get("price", 0))))

    def exchange_info(self) -> dict:
        return self._get_data("/market/exchange-info")
