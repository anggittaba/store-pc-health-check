"""Capture the README screenshots at 1280 px wide from a running dashboard.

    scripts/screenshots.sh     # builds a fresh demo database, serves it, captures, stops the server

Needs `pip install playwright` and Chromium (or CHROME=/path/to/chrome).
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8812")
    ap.add_argument("--store", required=True)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--copy-to", default="")
    ap.add_argument("--width", type=int, default=1280)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    chrome = os.getenv("CHROME")
    shots = [("/", "1-overview", 1500), ("/stores?severity=high", "2-stores", 1250),
             (f"/stores/{a.store}", "3-store-detail", 3000), ("/resume", "4-resume", 1300),
             ("/issues", "5-issue-types", 1000)]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome) if chrome else p.chromium.launch()
        page = browser.new_page(viewport={"width": a.width, "height": 900}, device_scale_factor=1)
        files = []
        for url, name, height in shots:
            page.set_viewport_size({"width": a.width, "height": 900})
            page.goto(a.base + url, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            h = min(height, page.evaluate("document.documentElement.scrollHeight"))
            page.set_viewport_size({"width": a.width, "height": h})
            page.wait_for_timeout(200)
            target = out / f"{name}.png"
            page.screenshot(path=str(target))
            files.append(target)
            print(target)
        browser.close()
    if a.copy_to:
        dest = Path(a.copy_to)
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy(f, dest / f.name)


if __name__ == "__main__":
    main()
