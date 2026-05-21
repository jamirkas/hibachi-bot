"""
Hibachi HMAC Authentication

Hibachi uses HMAC-SHA256 signing for Exchange Managed Accounts.
Each signed request needs: timestamp, method, path, body hash.
"""

import hashlib
import hmac
import time
import json


class HibachiAuth:
    """HMAC-based authentication for Hibachi Exchange Managed accounts."""

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key.encode() if isinstance(secret_key, str) else secret_key

    def sign(self, method: str, path: str, body: dict | None = None, timestamp: int | None = None) -> dict:
        """
        Produce headers with HMAC signature.

        Signature format (Hibachi convention):
          signature = HMAC-SHA256(secret, timestamp + method + path + body_hash)
          where body_hash = SHA256(json_body or '')
        """
        ts = timestamp or int(time.time() * 1000)
        body_str = json.dumps(body, separators=(',', ':')) if body else ''
        body_hash = hashlib.sha256(body_str.encode()).hexdigest()

        preimage = f"{ts}{method.upper()}{path}{body_hash}"
        signature = hmac.new(self.secret_key, preimage.encode(), hashlib.sha256).hexdigest()

        return {
            "X-API-KEY": self.api_key,
            "X-SIGNATURE": signature,
            "X-TIMESTAMP": str(ts),
            "Content-Type": "application/json",
        }
