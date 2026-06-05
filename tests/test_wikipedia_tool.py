import json
from unittest.mock import MagicMock

from tools.wikipedia_tool import WikipediaTool


def test_wikipedia_tool_uses_rest_fallback_on_json_error(monkeypatch):
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
