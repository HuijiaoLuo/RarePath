#!/usr/bin/env python3
"""Capture the exact facts the page sends for each eval disease, and the page's offline answers.

    pip install playwright && python -m playwright install chromium   # once; maintainers only
    python evals/capture_facts.py

The facts are built in the browser (demo/explore.html, buildFacts), so the eval reads them
from the page itself rather than re-implementing that logic. Writes evals/facts.json with
the graph version it was captured from; the eval refuses to score a stale snapshot.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "chat_cases.json"
OUT = ROOT / "evals" / "facts.json"


def main() -> int:
    from playwright.sync_api import sync_playwright

    cases = [c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"] if c["kind"] == "question"]
    page_url = (ROOT / "demo" / "explore.html").as_uri()
    out: dict = {"captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "focus": {}, "offline": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(page_url)
        page.wait_for_function("window.RAREPATH_EVAL !== undefined")
        out["graph_version"] = page.evaluate("RAREPATH_EVAL.graphVersion()")
        for focus in sorted({c["focus"] for c in cases}):
            out["focus"][focus] = page.evaluate("id => RAREPATH_EVAL.facts(id)", focus)
        for c in cases:
            out["offline"][c["id"]] = page.evaluate("([id, q]) => RAREPATH_EVAL.offline(id, q)", [c["focus"], c["question"]])
        browser.close()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Captured facts for {len(out['focus'])} diseases and {len(out['offline'])} offline answers (graph {out['graph_version']}) -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
