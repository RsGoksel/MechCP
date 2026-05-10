"""Manual end-to-end smoke test: spawn a browser, navigate, and clone a page section.

Run with the project venv active:

    python tests/manual_clone_smoke.py

This is intentionally NOT a pytest case because it spawns real Chromium and
hits the live internet. Use it to sanity-check the clone pipeline against a
specific URL before relying on the MCP path.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Sandbox writes into the project tree so we can inspect outputs.
os.environ["MECHCP_OUTPUT_DIR"] = str(ROOT / "mechcp_output")
os.environ.setdefault("MECHCP_LOG_LEVEL", "WARNING")

from browser_manager import BrowserManager
from element_cloner import element_cloner
from file_based_element_cloner import file_based_element_cloner
from models import BrowserOptions
from network_interceptor import NetworkInterceptor


URL = "https://www.frontiersin.org/for-authors/home"
TARGET_SELECTOR = "main"  # try the main content region first


async def main() -> int:
    bm = BrowserManager()
    ni = NetworkInterceptor()
    options = BrowserOptions(
        headless=True,
        user_agent=None,
        viewport_width=1366,
        viewport_height=900,
        proxy=None,
        block_resources=[],
        extra_headers={},
        user_data_dir=None,
        sandbox=False,  # auto-detect would suffice, but explicit for the test
    )

    print(f"[1/5] spawning browser ...", flush=True)
    instance = await bm.spawn_browser(options)
    instance_id = instance.instance_id
    tab = await bm.get_tab(instance_id)
    if tab is None:
        print("  ! could not obtain tab", flush=True)
        return 1
    await ni.setup_interception(tab, instance_id)

    print(f"[2/5] navigating to {URL} ...", flush=True)
    try:
        await tab.get(URL)
        await asyncio.sleep(3.0)  # let JS settle
    except Exception as exc:
        print(f"  ! navigation failed: {exc}", flush=True)
        await bm.close_instance(instance_id)
        return 2

    title = await tab.evaluate("document.title")
    final_url = await tab.evaluate("window.location.href")
    print(f"  -> title: {title!r}", flush=True)
    print(f"  -> final URL: {final_url}", flush=True)

    print(f"[3/5] cloning '{TARGET_SELECTOR}' (in-memory) ...", flush=True)
    try:
        clone_data = await element_cloner.clone_element_complete(
            tab,
            selector=TARGET_SELECTOR,
            extraction_options={
                "styles": {"include_computed": True, "include_pseudo": False},
                "structure": {"include_children": True, "max_depth": 4},
                "events": {"include_framework": True},
                "animations": {"analyze_keyframes": False},
                "assets": {"fetch_external": False},
                "related_files": {"follow_imports": False, "max_depth": 0},
            },
        )
    except Exception as exc:
        print(f"  ! clone failed: {exc}", flush=True)
        await bm.close_instance(instance_id)
        return 3

    print(f"  -> top-level keys: {sorted(clone_data.keys())[:8]}", flush=True)
    print(f"  -> approx size: {len(json.dumps(clone_data, default=str))} chars", flush=True)
    if "error" in clone_data:
        print(f"  ! cloner reported error: {clone_data['error']}", flush=True)

    print(f"[4/5] saving full clone to file ...", flush=True)
    try:
        result = await file_based_element_cloner.extract_complete_element_to_file(
            tab,
            selector=TARGET_SELECTOR,
            include_children=True,
        )
        if isinstance(result, dict) and "file_path" in result:
            print(f"  -> wrote {result['file_path']}", flush=True)
        else:
            print(f"  -> result: {str(result)[:300]}", flush=True)
    except Exception as exc:
        print(f"  ! file-based clone failed: {exc}", flush=True)

    print(f"[5/5] capturing network requests ...", flush=True)
    requests = await ni.list_requests(instance_id)
    print(f"  -> captured {len(requests)} network requests", flush=True)
    if requests:
        sample = [
            (r.method, r.resource_type, r.url[:80]) for r in requests[:5]
        ]
        for method, kind, url in sample:
            print(f"     {method:5s} {str(kind):12s} {url}", flush=True)

    await bm.close_instance(instance_id)
    print("\nDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
