"""One-use, expiring confirmations; transport independent."""

from __future__ import annotations

import secrets
import time


class HumanLoop:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds, self._pending = ttl_seconds, {}

    def request(self, action: dict, owner: str) -> str:
        token = secrets.token_urlsafe(18)
        self._pending[token] = (time.monotonic() + self.ttl_seconds, owner, action.copy())
        return token

    def resolve(self, token: str, approved: bool, owner: str) -> dict | None:
        item = self._pending.get(token)
        if not item or item[0] < time.monotonic() or item[1] != owner:
            return None
        self._pending.pop(token, None)
        if not approved:
            return None
        return item[2]
