import json
from unittest.mock import MagicMock

import requests

from tools.wikipedia_tool import WikipediaTool


def test_wikipedia_tool_uses_rest_fallback_on_json_decode_error(monkeypatch):
    """Test che se wikipedia.summary() crasha con JSON error, usiamo il fallback REST con successo."""
    monkeypatch.setattr(
        "tools.wikipedia_tool.wikipedia.summary",
        MagicMock(side_effect=json.JSONDecodeError("bad", "{}", 0)),
    )
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "extract": "Alessandro Manzoni e' stato uno scrittore italiano. Scrisse I promessi sposi. Altro testo."
    }
    mock_response.raise_for_status.return_value = None
    monkeypatch.setattr("tools.wikipedia_tool.requests.get", MagicMock(return_value=mock_response))

    result = WikipediaTool().execute({"query": "Alessandro Manzoni", "sentences": 2})

    assert result["status"] == "ok"
    assert result["source"] == "wikipedia-rest"
    assert "I promessi sposi" in result["message"]


def test_wikipedia_tool_uses_rest_fallback_on_generic_error(monkeypatch):
    """Test che se wikipedia.summary() crasha con errore generico, usiamo il fallback REST con successo."""
    monkeypatch.setattr(
        "tools.wikipedia_tool.wikipedia.summary",
        MagicMock(side_effect=Exception("generic error")),
    )
    mock_response = MagicMock()
    mock_response.json.return_value = {"extract": "Dante Alighieri scrisse la Divina Commedia."}
    mock_response.raise_for_status.return_value = None
    monkeypatch.setattr("tools.wikipedia_tool.requests.get", MagicMock(return_value=mock_response))

    result = WikipediaTool().execute({"query": "Dante Alighieri", "sentences": 1})

    assert result["status"] == "ok"
    assert result["source"] == "wikipedia-rest"
    assert "Divina Commedia" in result["message"]


def test_wikipedia_json_decode_error_is_friendly(monkeypatch):
    """Test che se ANCHE il fallback fallisce dopo un JSON error, l'errore finale e' amichevole."""
    monkeypatch.setattr(
        "tools.wikipedia_tool.wikipedia.summary",
        MagicMock(side_effect=json.JSONDecodeError("bad", "", 0)),
    )
    # Mockiamo requests per fallire, forzando il blocco except finale
    monkeypatch.setattr(
        "tools.wikipedia_tool.requests.get", MagicMock(side_effect=requests.RequestException("No internet"))
    )

    result = WikipediaTool().execute({"query": "porione"})

    assert result == {
        "status": "error",
        "message": "Wikipedia non disponibile: risposta non valida dal servizio.",
    }


def test_wikipedia_tool_searches_best_title_for_generic_query(monkeypatch):
    monkeypatch.setattr(
        "tools.wikipedia_tool.wikipedia.summary",
        MagicMock(side_effect=Exception("generic error")),
    )
    search_response = MagicMock()
    search_response.json.return_value = {"query": {"search": [{"title": "Fotosintesi clorofilliana"}]}}
    search_response.raise_for_status.return_value = None
    summary_response = MagicMock()
    summary_response.json.return_value = {
        "title": "Fotosintesi clorofilliana",
        "extract": "La fotosintesi clorofilliana e' un processo biologico. Produce glucosio e ossigeno.",
    }
    summary_response.raise_for_status.return_value = None
    mock_get = MagicMock(side_effect=[search_response, summary_response])
    monkeypatch.setattr("tools.wikipedia_tool.requests.get", mock_get)

    result = WikipediaTool().execute({"query": "fotosintesi", "sentences": 1})

    assert result["status"] == "ok"
    assert result["title"] == "Fotosintesi clorofilliana"
    assert result["message"] == "La fotosintesi clorofilliana e' un processo biologico."
