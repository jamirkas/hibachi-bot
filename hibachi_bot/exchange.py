"""
Hibachi Exchange REST API wrapper.
"""

import requests
import json
import time
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


class HibachiExchange:
    """REST API client for Hibachi."""

    REST_URL = "https://api.hibachi.xyz"
    DATA_URL = "https://data-api.hibachi.xyz"

    def __init__(self, api_key: str, secret_key: str, account_id: int):
        self.auth = HibachiAuth(api_key, secret_key)
        self.account_id = account_id
        self.session = requests.Session()

    # ---- helpers ----

    def _req(self, method: str, path: str, body: dict | None = None, base_url: str | None = None) -> dict:
        url = f"{base_url or self.REST_URL}{path}"
        headers = self.auth.sign(method, path, body)
        resp = self.session.request(method, url, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _get_data(self, path: str) -> dict:
        return self.session.get(f"{self.DATA_URL}{path}", timeout=10).json()

    # ---- account ----

    def balance(self) -> dict:
        return self._req("GET", f"/capital/balance?accountId={self.account_id}")

    def account_info(self) -> dict:
        return self._req("GET", f"/trade/account/info?accountId={self.account_id}")

    # ---- orders ----

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
        return self._req("DELETE", f"/trade/order?orderId={order_id}&accountId={self.account_id}")

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

    # ---- market data ----

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
