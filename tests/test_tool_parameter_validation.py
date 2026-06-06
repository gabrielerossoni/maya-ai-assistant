import json

from tools.param_utils import resolve_alias
from tools.translate_tool import TranslateTool
from tools.wikipedia_tool import WikipediaTool


def test_resolve_alias_prefers_top_level_then_nested_then_legacy_string():
    keys = ("query", "value")

    assert resolve_alias({"query": "top", "parametro": {"query": "nested"}}, keys) == "top"
    assert resolve_alias({"parametro": {"value": "nested"}}, keys) == "nested"
    assert resolve_alias({"parametro": "legacy"}, keys, allow_legacy_string=True) == "legacy"
    assert resolve_alias({"parametro": "legacy"}, keys, default="fallback") == "fallback"


def test_translate_prefers_canonical_text_over_conflicting_alias(monkeypatch):
    class FakeTranslator:
        def __init__(self, source, target):
            self.source = source
            self.target = target

        def translate(self, text):
            return f"{self.target}:{text}"

    monkeypatch.setattr("tools.translate_tool.GoogleTranslator", FakeTranslator)

    result = TranslateTool().execute({"text": "ciao", "query": "arrivederci", "target": "en"})

    assert result == {"status": "ok", "message": "en:ciao", "original": "ciao", "target": "en"}


def test_translate_uses_legacy_parametro_string_as_last_resort(monkeypatch):
    class FakeTranslator:
        def __init__(self, source, target):
            self.source = source
            self.target = target

        def translate(self, text):
            return f"{self.target}:{text}"

    monkeypatch.setattr("tools.translate_tool.GoogleTranslator", FakeTranslator)

    result = TranslateTool().execute({"parametro": "ciao", "target": "en"})

    assert result == {"status": "ok", "message": "en:ciao", "original": "ciao", "target": "en"}


def test_wikipedia_prefers_query_over_legacy_parametro(monkeypatch):
    monkeypatch.setattr("tools.wikipedia_tool.wikipedia.summary", lambda query, **_kwargs: f"summary:{query}")

    result = WikipediaTool().execute({"query": "Roma", "parametro": "Milano"})

    assert result["status"] == "ok"
    assert result["query"] == "Roma"
    assert result["message"] == "summary:Roma"


def test_wikipedia_json_decode_error_is_friendly(monkeypatch):
    monkeypatch.setattr(
        "tools.wikipedia_tool.wikipedia.summary",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(json.JSONDecodeError("bad", "", 0)),
    )
    # Mockiamo anche il fallback per farlo fallire, altrimenti otterremmo "ok" tramite REST
    import requests

    monkeypatch.setattr(
        "tools.wikipedia_tool.requests.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(requests.RequestException("No internet")),
    )

    result = WikipediaTool().execute({"query": "porione"})

    assert result == {
        "status": "error",
        "message": "Wikipedia non disponibile: risposta non valida dal servizio.",
    }
