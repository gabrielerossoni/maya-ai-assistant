"""Non-blocking startup diagnostics for local and optional integrations."""

from __future__ import annotations

import os
from pathlib import Path

from .memory.structured import StructuredMemory


def startup_health(database_path: str | Path = "data/structured_memory.sqlite3") -> dict:
    memory = StructuredMemory(database_path)
    try:
        memory.initialize()
        database = "ok"
    except OSError as exc:
        database = f"error:{type(exc).__name__}"
    telegram_token = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
    telegram_users = bool(os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip())
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "ollama_enabled": os.getenv("OLLAMA_ENABLED", "true").lower() in {"1", "true", "yes"},
        "telegram": "ready" if telegram_token and telegram_users else "not_configured",
    }
