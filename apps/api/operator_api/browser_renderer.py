"""Bounded Playwright fallback for same-origin, public HTTPS job pages."""

from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from .extraction import MAX_BYTES, public_target

MAX_SCREENSHOT_BYTES = 5_000_000
ALLOWED_TYPES = {"document", "script", "xhr", "fetch", "stylesheet"}


def request_allowed(url: str, hostname: str, resource_type: str) -> bool:
    try:
        target, _ = public_target(url)
    except (OSError, ValueError):
        return False
    return target.hostname == hostname and resource_type in ALLOWED_TYPES


def render(url: str) -> tuple[str, str, bytes]:
    parts, address = public_target(url)
    hostname = parts.hostname
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[f"--host-resolver-rules=MAP {hostname} {address}", "--disable-background-networking"],
        )
        try:
            context = browser.new_context(service_workers="block")
            page = context.new_page()

            def guard(route):
                request = route.request
                allowed = request_allowed(request.url, hostname, request.resource_type)
                route.continue_() if allowed else route.abort()

            page.route("**/*", guard)
            page.goto(url, wait_until="networkidle", timeout=20_000)
            final_url = page.url
            final = urlsplit(final_url)
            if final.hostname != hostname:
                raise ValueError("Browser navigation crossed the allowed origin")
            html = page.content()
            if len(html.encode("utf-8")) > MAX_BYTES:
                raise ValueError("Rendered job page exceeds the 2 MB limit")
            screenshot = page.screenshot(full_page=True, type="png")
            if len(screenshot) > MAX_SCREENSHOT_BYTES:
                raise ValueError("Rendered screenshot exceeds the 5 MB limit")
            return final_url, html, screenshot
        finally:
            browser.close()
