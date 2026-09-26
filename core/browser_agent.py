"""Read-only browser research with explicit target allowlists and no hidden actions."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class BrowserSafetyError(ValueError):
    pass


class BrowserAgent:
    def __init__(self, allowed_hosts: set[str] | None = None):
        self.allowed_hosts = allowed_hosts or set()

    def validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise BrowserSafetyError("Sono consentiti solo URL HTTPS pubblici.")
        if not self.allowed_hosts:
            raise BrowserSafetyError("Configura BROWSER_ALLOWED_HOSTS prima di usare browser.")
        hostname = parsed.hostname.casefold()
        if hostname not in self.allowed_hosts:
            raise BrowserSafetyError("Host non incluso nella policy browser.")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)}
        except ValueError:
            addresses = {hostname}
        except socket.gaierror as exc:
            raise BrowserSafetyError("Host browser non risolvibile.") from exc
        for address in addresses:
            try:
                if not ipaddress.ip_address(address).is_global:
                    raise BrowserSafetyError("Indirizzi non pubblici non consentiti.")
            except ValueError:
                raise BrowserSafetyError("Host browser non valido.")

    async def extract_text(self, url: str) -> str:
        self.validate_url(url)
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserSafetyError("Playwright non installato. Esegui bootstrap.") from exc
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()

                async def guarded_route(route):
                    try:
                        self.validate_url(route.request.url)
                        await route.continue_()
                    except BrowserSafetyError:
                        await route.abort()

                await page.route("**/*", guarded_route)
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                return (await page.locator("body").inner_text())[:20_000]
            finally:
                await browser.close()
