"""
test_dashboard_security.py - Verifica che i fix di sicurezza siano presenti
nel file HTML del dashboard (XSS, URL redirect, CDN SRI rimosso, ReDoS).
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DASHBOARD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static",
    "jarvis_dashboard.html",
)


@pytest.fixture(scope="module")
def html() -> str:
    with open(DASHBOARD, encoding="utf-8") as f:
        return f.read()


# ── CDN ───────────────────────────────────────────────────────────────────────


class TestCDN:
    def test_threejs_no_broken_integrity(self, html):
        """three.js non deve avere un hash SRI sbagliato che blocca il caricamento."""
        match = re.search(r'three\.min\.js[^>]*integrity="([^"]+)"', html)
        assert match is None, "three.js ha ancora un hash SRI — rischia di bloccare il caricamento se l'hash è errato"

    def test_threejs_has_crossorigin(self, html):
        assert 'three.min.js" crossorigin' in html

    def test_leaflet_no_broken_integrity(self, html):
        match = re.search(r'leaflet\.js[^>]*integrity="([^"]+)"', html)
        assert match is None, "leaflet.js ha un hash SRI che potrebbe bloccare il caricamento"


# ── XSS — innerHTML con escape ────────────────────────────────────────────────


class TestXSSEscape:
    def test_calendar_uses_esc_helper(self, html):
        """renderCalUpcoming deve usare _esc() prima di iniettare title/time nel DOM."""
        assert "_esc(" in html, "_esc helper non trovato nel dashboard"
        assert "const title = _esc(" in html
        assert "_esc(e.time)" in html

    def test_weather_forecast_uses_escape(self, html):
        """La previsione meteo deve escapare desc prima di innerHTML."""
        assert "const _e = s =>" in html or "const _e=" in html
        assert "_e((day.condition" in html or "_e( (day.condition" in html

    def test_news_sidebar_uses_en_helper(self, html):
        """updateNews deve usare _en() per source e title."""
        assert "const _en = s =>" in html
        assert "_en(a.source" in html
        assert "_en(a.title)" in html

    def test_news_ticker_uses_en_helper(self, html):
        assert "_en(a.source || 'NEWS')" in html
        assert "_en(a.title)" in html

    def test_no_raw_title_injection(self, html):
        """Non ci deve essere ${a.title} senza escape nel ticker o sidebar."""
        assert "${a.title}" not in html

    def test_no_raw_source_injection(self, html):
        assert "${a.source}" not in html


# ── URL redirect ──────────────────────────────────────────────────────────────


class TestURLRedirect:
    def test_browser_iframe_validates_url(self, html):
        """setLayout browser deve validare il protocollo prima di impostare iframe.src."""
        assert "new URL(params.url)" in html
        assert "_u.protocol === 'https:'" in html

    def test_news_link_uses_safeurl(self, html):
        """I link delle notizie devono passare per _safeUrl."""
        assert "const _safeUrl = u =>" in html
        assert "_safeUrl(a.link)" in html

    def test_safeurl_blocks_javascript_protocol(self, html):
        """_safeUrl deve permettere solo http/https."""
        assert "p.protocol==='https:'" in html
        assert "p.protocol==='http:'" in html

    def test_spotify_art_validates_url(self, html):
        """spotify-art.src deve validare che l'URL sia http/https."""
        assert "/^https?:\\/\\//.test(_artUrl)" in html


# ── ReDoS — agent_core.py ─────────────────────────────────────────────────────


class TestReDoS:
    def _read_agent_core(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core",
            "agent_core.py",
        )
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_no_vulnerable_findall_pattern(self):
        """re.findall(r'.*?\\s|.*$') è vulnerabile a ReDoS — non deve esistere."""
        src = self._read_agent_core()
        assert r"re.findall(r\".*?\s|.*$\"" not in src
        assert 're.findall(r".*?\\s|.*$"' not in src

    def test_spotify_regex_bounded(self):
        """La regex spotify deve avere una lunghezza massima per evitare ReDoS."""
        src = self._read_agent_core()
        assert r"[^\n]{1,200}" in src

    def test_uses_split_tokenizer(self):
        """Il tokenizer deve usare .split() invece di re.findall."""
        src = self._read_agent_core()
        assert "for w in final_reply.split()" in src


# ── CI permissions ────────────────────────────────────────────────────────────


class TestCIPermissions:
    def _read_ci(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".github",
            "workflows",
            "ci.yml",
        )
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_lint_job_has_permissions(self):
        ci = self._read_ci()
        lint_section = ci[ci.index("lint:") : ci.index("test:")]
        assert "permissions:" in lint_section
        assert "contents: read" in lint_section

    def test_test_job_has_permissions(self):
        ci = self._read_ci()
        test_section = ci[ci.index("test:") : ci.index("secrets-scan:")]
        assert "permissions:" in test_section
        assert "contents: read" in test_section

    def test_secrets_scan_job_has_permissions(self):
        ci = self._read_ci()
        scan_section = ci[ci.index("secrets-scan:") :]
        assert "permissions:" in scan_section
        assert "contents: read" in scan_section


# ── Socket binding ────────────────────────────────────────────────────────────


class TestSocketBinding:
    def test_network_tool_not_bound_to_all_interfaces(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tools",
            "network_tool.py",
        )
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "0.0.0.0" not in src, "run_server non deve fare binding su 0.0.0.0"
        assert "127.0.0.1" in src
