import os
import sys
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.news_tool import NewsTool, strip_tags


class Entry(dict):
    def __getattr__(self, name):
        return self[name]


def test_strip_tags_decodes_html_entities():
    assert strip_tags("L&#39;Ue concede &quot;fondi&quot;") == 'L\'Ue concede "fondi"'


def test_strip_tags_removes_markup_before_display():
    assert strip_tags("<p>Notizia <strong>importante</strong></p>") == "Notizia importante"


def test_news_tool_merges_italian_and_world_feeds(monkeypatch):
    monkeypatch.setenv("NEWS_FEED_URL", "https://example.test/italia.xml")
    monkeypatch.setenv("NEWS_WORLD_FEED_URL", "https://example.test/mondo.xml")

    def fake_parse(url):
        if "mondo" in url:
            return Entry(
                entries=[
                    Entry(
                        title="Vertice internazionale sulla tecnologia - Agenzia Mondo",
                        summary="",
                        link="https://example.test/world",
                        published="Thu, 04 Jun 2026 08:00:00 +0200",
                    )
                ]
            )
        return Entry(
            entries=[
                Entry(
                    title="Cronaca italiana del giorno - Fonte Italia",
                    summary="",
                    link="https://example.test/it",
                    published="Thu, 04 Jun 2026 07:00:00 +0200",
                )
            ]
        )

    tool = NewsTool()
    tool.initialize()
    with patch("tools.news_tool.feedparser.parse", side_effect=fake_parse):
        result = tool.execute({"limit": 5})

    assert result["status"] == "ok"
    assert len(result["news"]) == 2
    assert any("Mondo" in item["source"] for item in result["news"])


def test_news_tool_keeps_world_news_visible_with_many_italian_items(monkeypatch):
    monkeypatch.setenv("NEWS_FEED_URL", "https://example.test/italia.xml")
    monkeypatch.setenv("NEWS_WORLD_FEED_URL", "https://example.test/mondo.xml")

    def fake_parse(url):
        if "mondo" in url:
            return Entry(
                entries=[
                    Entry(
                        title="Vertice ONU sulla sicurezza globale - Reuters",
                        summary="",
                        link="https://example.test/world",
                        published="Thu, 04 Jun 2026 07:00:00 +0200",
                    )
                ]
            )
        return Entry(
            entries=[
                Entry(
                    title=f"Notizia italiana recente {i} - Fonte Italia",
                    summary="",
                    link=f"https://example.test/it-{i}",
                    published=f"Thu, 04 Jun 2026 0{9 - i}:00:00 +0200",
                )
                for i in range(5)
            ]
        )

    tool = NewsTool()
    tool.initialize()
    with patch("tools.news_tool.feedparser.parse", side_effect=fake_parse):
        result = tool.execute({"limit": 3})

    assert result["status"] == "ok"
    assert len(result["news"]) == 3
    assert any(item["source"].endswith("/ Mondo") for item in result["news"])
