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
                raw_summary = entry.get("summary", "")
                # Estrai immagine se presente
                image_url = None
                
                # 1. Prova regex nel summary
                img_match = re.search(r'<img[^>]+src="([^">]+)"', raw_summary)
                if img_match:
                    image_url = img_match.group(1)
                
                # 2. Prova media_content
                if not image_url and 'media_content' in entry and entry.media_content:
                    image_url = entry.media_content[0]['url']
                
                # 3. Prova enclosure
                if not image_url and 'enclosures' in entry and entry.enclosures:
                    image_url = entry.enclosures[0]['href']

                summary = self._clean_html(raw_summary)
                raw_title = self._clean_html(entry.get("title", ""))
                
                # Google News usa spesso "Titolo - Fonte"
                source = "Breaking News"
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0]
                    source = parts[1]

                news_list.append(f"- {title} ({source})")
                structured_news.append({
                    "title": title,
                    "source": source,
                    "link": entry.link,
                    "image": image_url,
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
