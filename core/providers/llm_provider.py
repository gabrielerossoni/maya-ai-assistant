"""Local Ollama first, explicit optional Groq fallback."""

from __future__ import annotations

from collections.abc import Awaitable, Callable


class LlmProvider:
    def __init__(self, local: Callable[..., Awaitable[dict | None]], fallback: Callable[..., Awaitable[dict | None]]):
        self.local, self.fallback = local, fallback

    async def complete(self, *args, **kwargs) -> tuple[dict | None, str]:
        result = await self.local(*args, **kwargs)
        if result is not None:
            return result, "ollama"
        return await self.fallback(*args, **kwargs), "groq"

    async def health(self) -> dict[str, bool]:
        try:
            return {"local": await self.local() is not None, "fallback": False}
        except Exception:
            return {"local": False, "fallback": False}
