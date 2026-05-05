"""
news_tool.py - Lettore di notizie RSS
"""

import feedparser
import os
import re
import html
from html.parser import HTMLParser

class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
    def handle_data(self, d):
        self.text.append(d)
    def get_data(self):
        return ''.join(self.text)

def strip_tags(html_content):
    if not html_content:
        return ""
    s = MLStripper()
    s.feed(html_content)
    return s.get_data().strip()

class NewsTool:
    def initialize(self):
        # Usiamo il feed ANSA come default
        self.feed_url = os.getenv("NEWS_FEED_URL", "https://www.ansa.it/sito/ansait_rss.xml")

    def _clean_html(self, raw_html):
        """Rimuove tag HTML e decodifica entità."""
        return strip_tags(raw_html)

    def execute(self, action: dict) -> dict:
        limit = action.get("limit", 5)
        try:
            feed = feedparser.parse(self.feed_url)
            if not feed.entries:
                return {"status": "error", "message": "Nessuna notizia trovata."}

            news_list = []
            structured_news = []
            for entry in feed.entries[:limit]:
                # Estrai sommario pulito
                summary = self._clean_html(entry.get("summary", ""))
                title = self._clean_html(entry.get("title", ""))
                
                news_list.append(f"- {title}")
                structured_news.append({
                    "title": title,
                    "link": entry.link,
                    "summary": summary[:200] + ("..." if len(summary) > 200 else ""),
                    "published": entry.get("published", "")
                })

            msg = "Ecco le ultime notizie:\n" + "\n".join(news_list)
            return {
                "status": "ok", 
                "message": msg, 
                "news": structured_news
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
