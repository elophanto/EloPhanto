#!/usr/bin/env python3
"""Exercise the built society UI against a real, isolated telemetry service.

Run from the repository root after ``cd web && npm run build``::

    .venv/bin/python web/scripts/society_smoke.py
    .venv/bin/python web/scripts/society_smoke.py --screenshots /tmp/society-review

Uses the project's Python Playwright dependency and installed Chromium. It does
not initialize an Agent, call providers, execute tools, or use the configured
browser/profile. All telemetry is safe test metadata; the HTTP port is ephemeral.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.async_api import Page, async_playwright, expect

from core.config import SocietyConfig
from core.society import SocietyService

TIMEOUT_MS = 45_000  # Software-rendered WebGL is slower than a desktop GPU.


def progress(message: str) -> None:
    print(f"[society smoke] {message}", flush=True)


def make_service(port: int = 0) -> SocietyService:
    return SocietyService(
        SocietyConfig(enabled=True, port=port, open_browser=False),
        PROJECT_ROOT,
        agent_name="EloPhanto",
    )


async def screenshot(page: Page, directory: Path, name: str) -> None:
    path = directory / f"society-smoke-{name}.png"
    await page.screenshot(
        path=str(path), full_page=True, animations="disabled", timeout=TIMEOUT_MS
    )
    progress(f"Screenshot: {path}")


async def connected(page: Page) -> None:
    await expect(page.get_by_role("status")).to_have_text("Connected to CLI")
    await expect(page.locator(".society-resident")).to_have_count(1)
    await expect(page.locator(".society-resident").first).to_contain_text("EloPhanto")


async def run(screenshots: Path) -> None:
    if not (PROJECT_ROOT / "web" / "dist" / "index.html").is_file():
        raise SystemExit("Build the UI first: cd web && npm run build")
    screenshots.mkdir(parents=True, exist_ok=True)
    service = make_service()
    if not service.start():
        raise SystemExit("Cannot bind the local smoke-test HTTP server")
    url = service.url
    port = urlsplit(url).port
    assert port is not None
    progress(f"Started isolated service: {url}")
    page_errors: list[str] = []
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--enable-unsafe-swiftshader"],
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 940},
                    device_scale_factor=1,
                )
                context.set_default_timeout(TIMEOUT_MS)
                expect.set_options(timeout=TIMEOUT_MS)
                page = await context.new_page()
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                # EventSource intentionally remains open; DOM readiness is the
                # navigation boundary, followed by explicit live-state checks.
                await page.goto(url, wait_until="domcontentloaded")
                await connected(page)
                canvas = page.locator(".society-canvas canvas")
                await expect(canvas).to_have_count(1)
                await expect(canvas).to_be_visible()
                await expect(canvas).to_have_attribute("role", "img")
                await expect(page.locator(".society-scene-error")).to_have_count(0)
                progress("Live connection, accessible WebGL canvas and resident verified")

                run_id = service.begin_run()
                ticket = service.begin_tool("browser_navigate")
                resident = page.locator(".society-resident").first
                await expect(resident).to_contain_text("Research")
                await expect(resident).to_contain_text("Working")
                await resident.click()
                spotlight = page.locator(".society-detail")
                await expect(spotlight).to_contain_text("Working in Research")
                await expect(spotlight.locator("code")).to_have_text("browser_navigate")
                await page.get_by_role("button", name="Visit department", exact=True).click()
                await expect(page.locator(".society-filter")).to_contain_text("Research")
                await page.get_by_role("button", name="Reset campus view", exact=True).click()
                await expect(page.locator(".society-filter")).to_have_count(0)
                await expect(spotlight).to_have_count(0)
                await screenshot(page, screenshots, "desktop")
                service.end_tool(ticket)
                service.end_run(run_id)
                await expect(resident).to_contain_text("Headquarters")
                await expect(resident).to_contain_text("At ease")
                progress("Actual tool departure, spotlight, department focus and return verified")

                # Start and finish in one synchronous burst: a viewer may only
                # receive the final idle actor, but the activity must survive.
                fast = service.begin_tool("shell_execute")
                service.end_tool(fast)
                activity = page.get_by_role("tab", name="Activity", exact=True)
                residents = page.get_by_role("tab", name=re.compile(r"^Residents\b"))
                await activity.click()
                await expect(
                    page.locator(".society-event").filter(has_text="shell execute").first
                ).to_be_visible()
                await expect(
                    page.locator(".society-event")
                    .filter(has_text="shell execute")
                    .filter(has_text="completed")
                    .first
                ).to_be_visible()
                await activity.press("ArrowLeft")
                await expect(residents).to_have_attribute("aria-selected", "true")
                await expect(residents).to_be_focused()
                await residents.press("End")
                await expect(activity).to_have_attribute("aria-selected", "true")
                await activity.press("Home")
                await expect(residents).to_have_attribute("aria-selected", "true")
                progress("Fast tool activity retention and keyboard tab navigation verified")

                await page.get_by_role("button", name="Pause animation", exact=True).click()
                resume = page.get_by_role("button", name="Resume animation", exact=True)
                await expect(resume).to_have_attribute("aria-pressed", "true")
                # A paused picture must still receive current telemetry.
                paused_ticket = service.begin_tool("knowledge_search")
                await expect(resident).to_contain_text("Knowledge")
                service.end_tool(paused_ticket)
                await expect(resident).to_contain_text("Headquarters")

                labels = page.get_by_role("button", name="Toggle department labels", exact=True)
                await labels.click()
                await expect(labels).to_have_attribute("aria-pressed", "false")
                await expect(page.locator(".society-department-label:visible")).to_have_count(0)
                await labels.click()
                await expect(labels).to_have_attribute("aria-pressed", "true")
                await expect(
                    page.locator(".society-department-label:visible").first
                ).to_be_visible()

                # Assert camera response through projected labels, without
                # requiring exact pixel positions or screenshot comparisons.
                anchor = page.locator(".society-department-label").first
                before_zoom = await anchor.evaluate("node => node.style.transform")
                await page.get_by_role("button", name="Zoom in", exact=True).click()
                await page.wait_for_function(
                    "before => document.querySelector('.society-department-label').style.transform !== before",
                    arg=before_zoom,
                )
                zoomed = await anchor.evaluate("node => node.style.transform")
                await page.get_by_role("button", name="Zoom out", exact=True).click()
                await page.wait_for_function(
                    "before => document.querySelector('.society-department-label').style.transform !== before",
                    arg=zoomed,
                )
                await page.get_by_role("button", name="Reset campus view", exact=True).click()
                progress("Pause keeps telemetry live; labels and camera zoom/reset respond")

                await page.get_by_role("button", name="About the society", exact=True).click()
                dialog = page.get_by_role("dialog")
                await expect(dialog).to_be_visible()
                await expect(
                    page.get_by_role("button", name="Close help", exact=True)
                ).to_be_focused()
                await page.keyboard.press("Escape")
                await expect(dialog).to_have_count(0)
                await expect(
                    page.get_by_role("button", name="About the society", exact=True)
                ).to_be_focused()
                await page.get_by_role("button", name="About the society", exact=True).click()
                await page.get_by_role("button", name="Take a demo tour", exact=True).click()
                await expect(page.get_by_role("status")).to_have_text("Demo campus")
                await expect(page.locator(".society-demo-notice")).to_contain_text(
                    "simulated residents"
                )
                await expect(page.locator(".society-resident")).to_have_count(8)
                await expect(residents).to_contain_text("8")
                await page.get_by_role("button", name="Switch to evening", exact=True).click()
                daylight = page.get_by_role("button", name="Switch to daylight", exact=True)
                await expect(daylight).to_have_attribute("aria-pressed", "true")
                await expect(page.locator(".society-app")).to_have_class(
                    re.compile(r"society-night")
                )
                await screenshot(page, screenshots, "night")
                await daylight.click()
                progress(
                    "Help focus/escape, explicitly labelled 8-resident demo and night mode verified"
                )

                await page.set_viewport_size({"width": 390, "height": 844})
                await expect(
                    page.get_by_role("button", name="About the society", exact=True)
                ).to_be_visible()
                await expect(page.locator(".society-resident")).to_have_count(8)
                dimensions = await page.evaluate(
                    "({width: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth})"
                )
                assert dimensions["document"] <= dimensions["width"] + 1, dimensions
                assert dimensions["body"] <= dimensions["width"] + 1, dimensions
                await screenshot(page, screenshots, "mobile")
                await page.set_viewport_size({"width": 1440, "height": 940})
                await page.get_by_role("button", name="Return to live", exact=True).click()
                await connected(page)
                await resume.click()
                await expect(
                    page.get_by_role("button", name="Pause animation", exact=True)
                ).to_have_attribute("aria-pressed", "false")
                progress("390px mobile has no horizontal overflow; return to live verified")

                await asyncio.to_thread(service.stop)
                await expect(page.get_by_role("status")).to_have_text("Reconnecting")
                await expect(page.locator(".society-offline-notice")).to_contain_text(
                    "reconnect automatically"
                )
                assert "Demo campus" not in await page.get_by_role("status").inner_text()
                progress("Stopped service produces offline notice without simulated data")
                service = make_service(port)
                assert service.start(), f"Could not restart isolated service at port {port}"
                await connected(page)
                reconnect_ticket = service.begin_tool("email_send")
                await expect(page.locator(".society-resident").first).to_contain_text(
                    "Communications"
                )
                service.end_tool(reconnect_ticket)
                progress("EventSource reconnects after same-port restart and receives fresh work")
                await page.close()

                # Exercise the accessible live-data fallback on a separate page
                # by emulating a browser whose WebGL context is unavailable.
                fallback = await context.new_page()
                fallback.on("pageerror", lambda error: page_errors.append(str(error)))
                await fallback.add_init_script("""(() => {
                    const original = HTMLCanvasElement.prototype.getContext;
                    HTMLCanvasElement.prototype.getContext = function(kind, ...args) {
                        if (/^(webgl2?|experimental-webgl)$/.test(kind)) return null;
                        return original.call(this, kind, ...args);
                    };
                })();""")
                await fallback.goto(url, wait_until="domcontentloaded")
                await connected(fallback)
                await expect(
                    fallback.get_by_role("heading", name="The campus needs WebGL", exact=True)
                ).to_be_visible()
                await expect(fallback.locator(".society-scene-error")).to_contain_text(
                    "Live activity is still available"
                )
                await fallback.locator(".society-resident").first.click()
                await expect(fallback.locator(".society-detail")).to_contain_text("EloPhanto")
                await fallback.get_by_role("tab", name="Activity", exact=True).click()
                await expect(fallback.locator(".society-event").first).to_be_visible()
                progress(
                    "WebGL-unavailable fallback preserves accessible live residents and activity"
                )
                await context.close()
                assert not page_errors, f"Uncaught browser errors: {page_errors}"
                print(
                    json.dumps(
                        {
                            "status": "passed",
                            "uncaught_browser_errors": page_errors,
                            "mobile_horizontal_overflow": False,
                            "screenshots": str(screenshots),
                            "checks": [
                                "live",
                                "tool_activity",
                                "spotlight",
                                "fast_events",
                                "keyboard_tabs",
                                "controls",
                                "demo",
                                "mobile",
                                "disconnect",
                                "reconnect",
                                "webgl_fallback",
                            ],
                        }
                    ),
                    flush=True,
                )
            finally:
                await browser.close()
    finally:
        await asyncio.to_thread(service.stop)
        progress("Isolated service stopped")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--screenshots",
        type=Path,
        default=Path("/tmp"),
        metavar="DIR",
        help="Screenshot output directory (default: /tmp)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.screenshots.expanduser().resolve()))


if __name__ == "__main__":
    main()
