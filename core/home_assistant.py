"""Home Assistant REST adapter; disabled until URL, token and entity allowlist exist."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx


class HomeAssistantAdapter:
    def __init__(self):
        self.url = os.getenv("HOME_ASSISTANT_URL", "").rstrip("/")
        self.token = os.getenv("HOME_ASSISTANT_TOKEN", "")
        self.entities = {value.strip() for value in os.getenv("HOME_ASSISTANT_ALLOWED_ENTITIES", "").split(",") if value.strip()}

    @property
    def enabled(self) -> bool:
        parsed = urlparse(self.url)
        return bool(parsed.scheme in {"http", "https"} and parsed.hostname and self.token and self.entities)

    async def set_state(self, entity_id: str, service: str) -> dict:
        if not self.enabled or entity_id not in self.entities:
            return {"status": "error", "message": "Home Assistant non configurato o entita non consentita."}
        domain = entity_id.split(".", 1)[0]
        if service not in {"turn_on", "turn_off", "toggle"}:
            return {"status": "error", "message": "Servizio Home Assistant non consentito."}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{self.url}/api/services/{domain}/{service}",
                    headers={"Authorization": f"Bearer {self.token}"}, json={"entity_id": entity_id},
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return {"status": "error", "message": "Home Assistant non raggiungibile."}
        return {"status": "ok", "message": f"{entity_id}: {service}"}
