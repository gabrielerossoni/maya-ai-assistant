"""Pure parsing for local, no-LLM commands."""

from __future__ import annotations

import re
from datetime import datetime, timedelta


class FastPathRouter:
    """Parse only commands whose result is deterministic and local."""

    @staticmethod
    def structured_memory(text: str) -> tuple[str, dict] | None:
        reminder = re.fullmatch(
            r"ricordami\s+(oggi|domani)(?:\s+alle\s+(\d{1,2})(?::(\d{2}))?)?\s+(?:che\s+)?(.+)", text
        )
        if reminder:
            day, hour, minute, content = reminder.groups()
            if hour is not None and not (0 <= int(hour) <= 23 and 0 <= int(minute or 0) <= 59):
                return "invalid", {"message": "Orario promemoria non valido."}
            due_at = datetime.now().astimezone().replace(second=0, microsecond=0)
            if day == "domani":
                due_at += timedelta(days=1)
            due_at = due_at.replace(hour=int(hour or 9), minute=int(minute or 0))
            if day == "oggi" and due_at <= datetime.now().astimezone():
                return "invalid", {"message": "L'orario di oggi e gia passato."}
            return "reminder", {"content": content.strip(), "due_at": due_at}
        note = re.fullmatch(r"(?:segnati|annota|prendi nota)(?:\s+che)?\s+(.+)", text)
        if note:
            content = note.group(1).strip()
            lent = re.fullmatch(r"ho prestato (?:il|lo|la|i|gli|le)\s+(.+?)\s+a\s+(.+)", content)
            return ("fact", {"subject": lent.group(1), "value": f"Prestato a {lent.group(2)}"}) if lent else ("note", {"content": content})
        malformed_lookup = re.fullmatch(r"dov['\uFFFD]\s+(?:il|lo|la|i|gli|le)?\s*(.+?)[?!.]*", text)
        if malformed_lookup:
            return "fact_lookup", {"query": malformed_lookup.group(1).strip()}
        normal_lookup = re.fullmatch(r"dov(?:e|['’][eè])\s+(?:il|lo|la|i|gli|le)?\s*(.+?)[?!.]*", text)
        if normal_lookup:
            return "fact_lookup", {"query": normal_lookup.group(1).strip()}
        lookup = re.fullmatch(r"(?:dove|dov['â€™][eÃ¨])\s+(?:il|lo|la|i|gli|le)?\s*(.+?)[?!.]*", text)
        return ("fact_lookup", {"query": lookup.group(1).strip()}) if lookup else None

    @staticmethod
    def calendar(text: str) -> tuple[dict | None, str] | None:
        if re.search(r"\b(?:prossim[oi]|mostra|lista|elenca|cos[' ]?ho|cosa ho|ho)\b", text) and re.search(
            r"\b(?:calendario|eventi|agenda)\b", text
        ):
            return {"tool": "calendar", "action": "list"}, "Ecco i prossimi eventi."
        if re.search(r"\b(?:cancella|elimina|rimuovi)\b", text) and re.search(r"\b(?:evento|appuntamento)\b", text):
            title = re.sub(r"\b(?:cancella|elimina|rimuovi|evento|appuntamento|il|la)\b", " ", text)
            title = re.sub(r"\s+", " ", title).strip(" .,;:-")
            return ({"tool": "calendar", "action": "delete", "title": title}, f"Cancello l'evento '{title}'.") if title else (None, "Dimmi il titolo dell'evento da cancellare.")
        return None
