"""
token_juice.py - Compressione tool output prima dell'LLM.
Riduce token nel context per tool informativi (news, weather, search, ecc.).
Ispirato al layer TokenJuice di OpenHuman.
"""

import re

_TOOL_CHAR_LIMITS = {
    "news": 600,
    "weather": 400,
    "search": 800,
    "wikipedia": 500,
    "trading": 200,
}
_DEFAULT_LIMIT = 1000


def compress_tool_output(tool_name: str, raw: str) -> str:
    """Comprime output tool prima di inserirlo nel context LLM."""
    if not raw:
        return raw

    # Rimuovi HTML residuo
    raw = re.sub(r"<[^>]+>", "", raw)

    # Abbrevia URL lunghi (mantieni solo dominio)
    raw = re.sub(r"https?://([^/\s]+)[^\s]*", r"[\1]", raw)

    # Comprimi whitespace multiplo
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    raw = re.sub(r"  +", " ", raw)

    max_chars = _TOOL_CHAR_LIMITS.get(tool_name, _DEFAULT_LIMIT)
    if len(raw) > max_chars:
        raw = raw[:max_chars] + "...[troncato]"

    return raw.strip()
