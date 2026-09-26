"""Read-only browser extraction; never performs clicks, logins or form input."""

import os

from core.browser_agent import BrowserAgent, BrowserSafetyError


class BrowserTool:
    def __init__(self):
        hosts = {item.strip() for item in os.getenv("BROWSER_ALLOWED_HOSTS", "").split(",") if item.strip()}
        self.agent = BrowserAgent(hosts)

    def initialize(self):
        pass

    async def execute(self, action: dict) -> dict:
        try:
            text = await self.agent.extract_text(str(action.get("url", "")))
            return {"status": "ok", "message": text}
        except BrowserSafetyError as exc:
            return {"status": "error", "message": str(exc)}
