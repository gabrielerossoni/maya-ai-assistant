"""
news_tool.py - Lettore di notizie RSS
"""

import feedparser
import os


class NewsTool:
    def initialize(self):
        # Usiamo il feed ANSA come default
        self.feed_url = os.getenv("NEWS_FEED_URL", "https://www.ansa.it/sito/ansait_rss.xml")

    def execute(self, action: dict) -> dict:
        limit = action.get("limit", 3)
        try:
            feed = feedparser.parse(self.feed_url)
            if not feed.entries:
                return {"status": "error", "message": "Nessuna notizia trovata."}

            news_list = []
            for i, entry in enumerate(feed.entries[:limit]):
                news_list.append(f"- {entry.title}")

            msg = "Ecco le ultime notizie:\n" + "\n".join(news_list)
            return {"status": "ok", "message": msg}
        except Exception as e:
            return {"status": "error", "message": str(e)}
