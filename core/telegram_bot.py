"""Minimal Telegram bridge using Bot API directly; optional until env is configured."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx

from .audit.logger import AuditLogger
from .permissions.human_loop import HumanLoop


class TelegramBot:
    def __init__(self, agent, voice_manager=None, audit: AuditLogger | None = None):
        self.agent, self.voice_manager = agent, voice_manager
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.allowed_users = {
            value.strip() for value in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if value.strip()
        }
        self.timeout = float(os.getenv("TELEGRAM_TIMEOUT_SECONDS", "15"))
        self.audit = audit or AuditLogger()
        self.confirmations = HumanLoop()
        try:
            self.offset = max(0, int(self.agent.structured_memory.get_preference("telegram_offset") or 0))
        except (AttributeError, TypeError, ValueError):
            self.offset = 0

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.allowed_users)

    def health(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "authorized_users": len(self.allowed_users),
            "token_configured": bool(self.token),
        }

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _allowed(self, message: dict) -> bool:
        return str(message.get("from", {}).get("id", "")) in self.allowed_users

    async def send(self, chat_id: int | str, text: str) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for chunk in (text[index : index + 4096] for index in range(0, max(1, len(text)), 4096)):
                response = await client.post(self._url("sendMessage"), json={"chat_id": chat_id, "text": chunk or " "})
                response.raise_for_status()

    async def deliver_default(self, text: str) -> None:
        chat_id = os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "").strip()
        if self.enabled and chat_id in self.allowed_users:
            await self.send(chat_id, text)

    async def _reply_from_agent(self, chat_id: int | str, user_id: int | str, text: str) -> None:
        chunks = [chunk async for chunk in self.agent.process(text, source=f"telegram:{chat_id}:{user_id}")]
        await self.send(chat_id, "".join(chunks).strip() or "Nessuna risposta.")
        self.audit.record("telegram_reply", actor=str(chat_id), details={"kind": "text"})

    async def request_confirmation(self, chat_id: int | str, user_id: int | str, action: dict) -> None:
        token = self.confirmations.request(action, str(user_id))
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Conferma", "callback_data": f"confirm:{token}"},
                    {"text": "Annulla", "callback_data": f"cancel:{token}"},
                ]
            ]
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._url("sendMessage"),
                json={"chat_id": chat_id, "text": "Azione sensibile. Confermi?", "reply_markup": keyboard},
            )
            response.raise_for_status()

    async def _handle_callback(self, callback: dict) -> None:
        if not self._allowed(callback):
            return
        data = str(callback.get("data", ""))
        operation, _, token = data.partition(":")
        action = self.confirmations.resolve(token, operation == "confirm", str(callback.get("from", {}).get("id", "")))
        callback_id = callback.get("id")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if callback_id:
                await client.post(self._url("answerCallbackQuery"), json={"callback_query_id": callback_id})
        if action:
            result = await self.agent.tool_manager.execute(action)
            chat_id = callback["message"]["chat"]["id"]
            await self.send(chat_id, result.get("message", "Azione completata."))
            self.audit.record(
                "telegram_confirmation_executed", actor=str(chat_id), details={"tool": action.get("tool")}
            )

    async def _handle_voice(self, chat_id: int | str, user_id: int | str, voice: dict) -> None:
        if not self.voice_manager:
            await self.send(chat_id, "Note vocali non disponibili.")
            return
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if int(voice.get("file_size", 0)) > int(os.getenv("TELEGRAM_MAX_VOICE_BYTES", "20971520")):
                await self.send(chat_id, "Nota vocale troppo grande.")
                return
            response = await client.get(self._url("getFile"), params={"file_id": voice["file_id"]})
            response.raise_for_status()
            result = response.json()
            file_path = result.get("result", {}).get("file_path")
            if not file_path:
                await self.send(chat_id, "Download nota vocale fallito.")
                return
            download = await client.get(f"https://api.telegram.org/file/bot{self.token}/{file_path}")
            download.raise_for_status()
            data = download.content
        descriptor, filename = tempfile.mkstemp(suffix=".ogg", prefix="maya-telegram-")
        os.close(descriptor)
        temp_path = Path(filename)
        try:
            temp_path.write_bytes(data)
            text = await asyncio.to_thread(self.voice_manager.transcribe_file, str(temp_path))
            await self._reply_from_agent(chat_id, user_id, text or "Non ho capito la nota vocale.")
            self.audit.record("telegram_voice_processed", actor=str(chat_id))
        finally:
            temp_path.unlink(missing_ok=True)

    async def handle_update(self, update: dict) -> None:
        if update.get("callback_query"):
            await self._handle_callback(update["callback_query"])
            return
        message = update.get("message") or update.get("edited_message")
        if not message or not self._allowed(message):
            if message:
                self.audit.record("telegram_denied", actor=str(message.get("from", {}).get("id", "unknown")))
            return
        chat_id = message["chat"]["id"]
        if message.get("text"):
            try:
                await self._reply_from_agent(chat_id, message["from"]["id"], message["text"])
            except httpx.HTTPError:
                self.audit.record("telegram_delivery_error", actor=str(chat_id))
        elif message.get("voice"):
            await self._handle_voice(chat_id, message["from"]["id"], message["voice"])

    async def start(self) -> None:
        if not self.enabled:
            return
        while True:
            try:
                async with httpx.AsyncClient(timeout=max(self.timeout + 10, 30)) as client:
                    response = await client.get(self._url("getUpdates"), params={"offset": self.offset, "timeout": 20})
                    response.raise_for_status()
                    updates = response.json().get("result", [])
                for update in updates:
                    await self.handle_update(update)
                    self.offset = max(self.offset, int(update["update_id"]) + 1)
                    self.agent.structured_memory.set_preference("telegram_offset", str(self.offset))
            except (httpx.HTTPError, ValueError):
                await asyncio.sleep(3)
