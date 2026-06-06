"""
news_tool.py - Lettore di notizie RSS per dashboard e risposte vocali.
"""

import asyncio
import html
import os
import re
from collections import defaultdict
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

import feedparser
import httpx


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
        return "".join(self.text)


def strip_tags(html_content):
    if not html_content:
        return ""
    s = MLStripper()
    s.feed(html.unescape(str(html_content)))
    return html.unescape(s.get_data()).strip()


class NewsTool:
    def initialize(self):
        self.feed_url = os.getenv("NEWS_FEED_URL", "https://www.ansa.it/sito/ansait_rss.xml")
        self.feed_urls = self._configured_feeds()

    def _configured_feeds(self) -> list[tuple[str, str]]:
        primary = os.getenv("NEWS_FEED_URL", "https://www.ansa.it/sito/ansait_rss.xml")
        world = os.getenv(
            "NEWS_WORLD_FEED_URL",
            "https://news.google.com/rss/headlines/section/topic/WORLD?hl=it&gl=IT&ceid=IT:it",
        )
        extra = os.getenv("NEWS_EXTRA_FEEDS", "")

        feeds = [("ITALIA", primary), ("MONDO", world)]
        for item in extra.split(","):
            url = item.strip()
            if url:
                feeds.append(("EXTRA", url))

        seen = set()
        unique = []
        for label, url in feeds:
            if url not in seen:
                seen.add(url)
                unique.append((label, url))
        return unique

    def _clean_html(self, raw_html):
        return strip_tags(raw_html)

    def _entry_datetime(self, entry):
        for key in ("published", "updated", "created"):
            value = entry.get(key)
            if value:
                try:
                    return parsedate_to_datetime(value)
                except Exception:
                    pass
        return None

    def _entry_to_news_item(self, feed_label, entry):
        raw_summary = entry.get("summary", "")
        image_url = None

        img_match = re.search(r'<img[^>]+src="([^">]+)"', raw_summary)
        if img_match:
            image_url = html.unescape(img_match.group(1))

        if not image_url and "media_content" in entry and entry.media_content:
            image_url = entry.media_content[0]["url"]

        if not image_url and "enclosures" in entry and entry.enclosures:
            image_url = entry.enclosures[0]["href"]

        summary = self._clean_html(raw_summary)
        raw_title = self._clean_html(entry.get("title", ""))

        source = "Breaking News"
        title = raw_title
        if " - " in raw_title:
            parts = raw_title.rsplit(" - ", 1)
            title = parts[0]
            source = parts[1]

        if feed_label == "MONDO" and "mondo" not in source.lower():
            source = f"{source} / Mondo"

        return {
            "title": title,
            "source": source,
            "link": entry.link,
            "image": image_url,
            "summary": summary[:200] + ("..." if len(summary) > 200 else ""),
            "published": entry.get("published", ""),
            "_feed_label": feed_label,
            "_dt": self._entry_datetime(entry),
        }

    def _select_balanced_news(self, items, limit):
        grouped = defaultdict(list)
        for item in items:
            grouped[item["_feed_label"]].append(item)

        epoch = parsedate_to_datetime("Thu, 01 Jan 1970 00:00:00 +0000")
        for group_items in grouped.values():
            group_items.sort(key=lambda item: item["_dt"] or epoch, reverse=True)

        ordered_labels = [label for label, _url in getattr(self, "feed_urls", []) if grouped.get(label)]
        selected = []
        seen_titles = set()

        while len(selected) < limit and any(grouped.get(label) for label in ordered_labels):
            for label in ordered_labels:
                if len(selected) >= limit:
                    break
                while grouped.get(label):
                    item = grouped[label].pop(0)
                    title_key = re.sub(r"\W+", "", item["title"].lower())
                    if title_key and title_key not in seen_titles:
                        seen_titles.add(title_key)
                        selected.append(item)
                        break

        return selected

    async def _fetch_feed(self, client: httpx.AsyncClient, feed_url: str):
        res = await client.get(feed_url)
        res.raise_for_status()
        return feedparser.parse(res.content)

    async def execute_async(self, action: dict) -> dict:
        limit = action.get("limit", 5)
        try:
            parsed_items = []
            feeds = getattr(self, "feed_urls", None) or self._configured_feeds()
            timeout = float(os.getenv("NEWS_FEED_TIMEOUT", "6.0"))
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                results = await asyncio.gather(
                    *(self._fetch_feed(client, feed_url) for _feed_label, feed_url in feeds),
                    return_exceptions=True,
                )

            for (feed_label, _feed_url), feed in zip(feeds, results):
                if isinstance(feed, Exception):
                    continue
                for entry in feed.entries:
                    parsed_items.append(self._entry_to_news_item(feed_label, entry))

            if not parsed_items:
                return {"status": "error", "message": "Nessuna notizia trovata."}

            structured_news = self._select_balanced_news(parsed_items, limit)
            news_list = [f"- {item['title']} ({item['source']})" for item in structured_news]
            for item in structured_news:
                item.pop("_feed_label", None)
                item.pop("_dt", None)

            msg = "Ecco le ultime notizie:\n" + "\n".join(news_list)
            return {"status": "ok", "message": msg, "news": structured_news}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def execute(self, action: dict) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.execute_async(action))
        return {
            "status": "error",
            "message": "NewsTool.execute non puo bloccare un event loop attivo; usare execute_async.",
        }
