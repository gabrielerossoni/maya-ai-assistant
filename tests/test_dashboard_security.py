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
    "maya_dashboard.html",
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

    def test_calendar_visual_badges_are_present(self, html):
        assert "cal-day-count" in html
        assert "GOOGLE ${googleCount}" in html
        assert "grid-template-columns: minmax(300px, 360px) 1fr" in html

    def test_weather_forecast_uses_escape(self, html):
        """La previsione meteo deve escapare desc prima di innerHTML."""
        assert "const _e = s =>" in html or "const _e=" in html
        assert "_e((day.condition" in html or "_e( (day.condition" in html

    def test_weather_forecast_has_dynamic_ui(self, html):
        assert "wx-fc-icon" in html
        assert "wx-fc-bar-fill" in html
        assert "wx-fc-legend" in html
        assert "forecastTempColor(maxTemp)" in html
        assert "forecastTempFill(maxTemp)" in html
        assert "Fresco" in html
        assert "Mite" in html
        assert "Caldo" in html
        assert "day.precip_probability" in html
        assert "PIOGGIA" in html

    def test_news_sidebar_uses_en_helper(self, html):
        """updateNews deve usare _en() per source e title."""
        assert "const _en = s =>" in html
        assert "_en(a.source" in html
        assert "_en(a.title)" in html

    def test_news_ticker_uses_en_helper(self, html):
        assert "_en(a.source || 'NEWS')" in html
        assert "_en(a.title)" in html

    def test_news_text_is_decoded_before_textcontent(self, html):
        """Le entity HTML devono essere sicure ma non visibili come L&#39;utente."""
        assert "const _decodeHtml = s =>" in html
        assert "titleDiv.textContent = _safeText(a.title)" in html
        assert "sourceDiv.textContent = _safeText(a.source || 'MAYA FEED')" in html

    def test_news_sidebar_supports_optional_thumbnail(self, html):
        """La lista notizie deve poter mostrare una miniatura validata."""
        assert "const _img = _safeUrl(a.image)" in html
        assert "thumb.className = 'ns-thumb'" in html
        assert "thumb.referrerPolicy = 'no-referrer'" in html

    def test_news_ticker_has_scroll_animation(self, html):
        assert "animation: scroll-ticker" in html
        assert "@keyframes scroll-ticker" in html
        assert "transform: translateX(-50%)" in html

    def test_news_live_streams_use_live_channel_embeds_only(self, html):
        assert "youtube.com/embed/live_stream?channel=" in html
        assert "UCoMdktPbSTixAyNGwb-UYkQ" not in html
        assert "UCSrZ3UV4jOidv8ppoVuvW9Q" in html
        assert "UC7fWeaHhqgM4Ry-RMpM2YYw" in html
        assert "UCknLrEdhRCp1aegoMqRaCZg" not in html
        assert "UC16niRr50-MSBwiO3YDb3RA" in html
        assert "NEWS_BLOCKED_STREAMS.has(stream.src)" in html
        assert "BBC NEWS" not in html
        assert "SKY NEWS" not in html
        assert "DW NEWS" not in html
        assert "UCLXo7UDZvByw2ixzpQCufnA" not in html
        assert "fetch('/api/news/live-streams'" in html
        assert "stream.fallback ? ' · FALLBACK LIVE'" not in html
        assert "kind: 'video'" not in html
        assert "oembed?url=" not in html

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


class TestDirectToolAllowlist:
    def test_dashboard_blocks_powerful_tools(self):
        from core.routes import _validate_direct_tool_action

        allowed, reason = _validate_direct_tool_action({"tool": "system", "command": "shutdown"})
        assert not allowed
        assert "non consentito" in reason

    def test_dashboard_allows_known_controls(self):
        from core.routes import _validate_direct_tool_action

        assert _validate_direct_tool_action({"tool": "calendar", "action": "list"})[0]
        assert _validate_direct_tool_action({"tool": "spotify", "command": "current"})[0]
        assert _validate_direct_tool_action({"tool": "arduino", "op": "SET", "target": "light", "value": 1})[0]

    def test_dashboard_blocks_unknown_arduino_target(self):
        from core.routes import _validate_direct_tool_action

        allowed, reason = _validate_direct_tool_action({"tool": "arduino", "op": "SET", "target": "../bad"})
        assert not allowed
        assert "target Arduino" in reason


class TestSceneControls:
    def test_night_scene_is_single_dashboard_chip(self, html):
        assert 'id="chip-notte"' not in html
        assert 'id="chip-buonanotte"' in html
        assert "Buonanotte" in html

    def test_dashboard_has_scene_off_control(self, html):
        assert "spegni scena" in html
        assert "scene_cleared" in html
        assert "clearScenePill" in html

    def test_dashboard_uses_device_cards_without_relay(self, html):
        assert "dom-cards-grid" in html
        assert "dom-floorplan" not in html
        assert "dev-relay" not in html
        assert "target: 'relay'" not in html
        for label in [
            "Luce",
            "Cancello",
            "Porta",
            "Buzzer",
            "Audio",
            "Soggiorno",
            "Camera",
            "Giardino",
        ]:
            assert label in html

    def test_dashboard_device_cards_have_organized_layout_css(self, html):
        assert "--dom-card-bg" in html
        assert "grid-auto-rows: minmax(126px, auto)" in html
        assert "grid-template-columns: repeat(var(--dom-cols, 3), minmax(0, 1fr))" in html
        assert "border: 1px solid var(--dom-card-border)" in html
        assert "grid-template-columns: minmax(0, 1fr) var(--sb-width, 260px)" in html

    def test_rgb_cards_cycle_multiple_colors(self, html):
        assert "const RGB_CYCLE" in html
        assert "function nextRgbAction" in html
        assert "rgb: { r:" in html
        assert "value: RGB_CYCLE[next].rgb" in html
        assert "color.rgb.r === normalized[0]" in html
        assert "value: 16711680" not in html
        assert "setRgbCardState(dev, action._rgbIndex)" in html
        for label in ["ROSSO", "VERDE", "BLU", "VIOLA", "ARANCIO", "BIANCO"]:
            assert label in html

    def test_rgb_cards_hold_to_turn_off(self, html):
        assert "function setupRgbHoldControls" in html
        assert "function turnRgbOff" in html
        assert "rgbSuppressClick[dev] = true" in html
        assert "sendArduinoAction({ op: 'SET', target: dev, value: 0 })" in html
