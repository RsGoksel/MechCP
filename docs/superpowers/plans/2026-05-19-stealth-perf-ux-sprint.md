# MechCP Sprint B: Stealth MED + Perf HIGH + Agent-UX HIGH Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every remaining HIGH-impact item from the prior three-axis audit (stealth/performance/UX) without breaking the 48-test smoke suite or the live `frontiersin.org` clone test.

**Architecture:** All tasks are additive or local refactors inside `src/`. New tools are added as `@section_tool(...)` functions in `src/server.py` (the `tools/` migration is a separate sprint). Stealth helpers extend `src/stealth_scripts.py`. The network-idle and Fetch-state helpers reuse existing primitives in `network_interceptor.py` and `dynamic_hook_system.py`. New tests target only the deterministic surfaces (path validators, AST checks, env-resolution); browser-spawning tests stay in the manual smoke script.

**Tech Stack:** Python 3.10+, FastMCP, nodriver 0.47.x, pydantic v2, pytest + pytest-asyncio. CDP commands via `uc.cdp.*`.

**Scope decisions (deferred to next sprint):**
- **Iframe entry** (`list_frames` + `frame` arg on every interaction tool) and **Shadow DOM piercing** are cross-cutting refactors that touch every DOM/interaction tool and require coordinated test coverage. Deferring keeps this sprint focused on small, well-scoped, independently-shippable improvements.
- **Full `tools/` package migration of the remaining 10 server.py sections** stays on its existing track (sprint.md §2).

---

## File Structure (deltas in this sprint)

```
src/
  stealth_scripts.py          # Extend: client-hints parser, Bezier mouse helper
  browser_manager.py          # Modify: pass user_agent_metadata when UA overridden
  network_interceptor.py      # Modify: in_flight counter for real network-idle
  dom_handler.py              # Modify: wait_for_element MutationObserver, click verify, Bezier click
  element_cloner.py           # Modify: route fallback fetches through tab.evaluate
  server.py                   # Modify: argparse-before-decorators for --minimal,
                              #         real wait_until=networkidle, navigate referrer,
                              #         new tools (get_visible_text, get_page_outline,
                              #         screenshot_element, get_console_logs),
                              #         block_resources docstring + warning
tests/
  test_stealth_scripts.py     # Create: UA-metadata parsing
  test_network_idle.py        # Create: in-flight counter unit test (no browser)
```

---

## Task 1: Real `wait_until="networkidle"`

**Why:** `server.py:302` currently does a literal `asyncio.sleep(2)`. Agents that ask for network-idle get fooled into acting too early. The `NetworkInterceptor` already tracks `_instance_requests` so an in-flight counter is cheap to bolt on.

**Files:**
- Modify: `src/network_interceptor.py` (add in-flight tracking + helper)
- Modify: `src/server.py` (use the helper in `navigate`)
- Create: `tests/test_network_idle.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_network_idle.py`:

```python
"""NetworkInterceptor exposes an in-flight counter for real network-idle waits."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


@pytest.mark.asyncio
async def test_in_flight_counter_increments_and_decrements():
    from network_interceptor import NetworkInterceptor

    ni = NetworkInterceptor()
    assert ni.in_flight_count("inst-1") == 0
    ni._inc_in_flight("inst-1")
    ni._inc_in_flight("inst-1")
    assert ni.in_flight_count("inst-1") == 2
    ni._dec_in_flight("inst-1")
    assert ni.in_flight_count("inst-1") == 1
    ni._dec_in_flight("inst-1")
    ni._dec_in_flight("inst-1")  # never goes negative
    assert ni.in_flight_count("inst-1") == 0


@pytest.mark.asyncio
async def test_wait_for_idle_resolves_when_counter_drops():
    from network_interceptor import NetworkInterceptor

    ni = NetworkInterceptor()
    ni._inc_in_flight("inst-1")

    async def drop_later():
        await asyncio.sleep(0.05)
        ni._dec_in_flight("inst-1")

    asyncio.create_task(drop_later())
    settled = await ni.wait_for_idle("inst-1", idle_ms=50, timeout_ms=2000)
    assert settled is True


@pytest.mark.asyncio
async def test_wait_for_idle_times_out_when_traffic_never_settles():
    from network_interceptor import NetworkInterceptor

    ni = NetworkInterceptor()
    ni._inc_in_flight("inst-1")

    settled = await ni.wait_for_idle("inst-1", idle_ms=50, timeout_ms=200)
    assert settled is False
```

- [ ] **Step 2: Run the test to verify it fails**

```
python -m pytest tests/test_network_idle.py -v
```
Expected: FAIL with `AttributeError: 'NetworkInterceptor' object has no attribute 'in_flight_count'`.

- [ ] **Step 3: Implement the in-flight counter and `wait_for_idle`**

Edit `src/network_interceptor.py`:

Add to imports near the top (after the existing `from typing import ...`):

```python
import time
from collections import defaultdict
```

Inside `NetworkInterceptor.__init__`, after the existing `self._max_requests_per_instance = ...` line, add:

```python
        self._in_flight: Dict[str, int] = defaultdict(int)
        self._last_change: Dict[str, float] = defaultdict(lambda: time.monotonic())
```

Add three new methods to `NetworkInterceptor` (anywhere between existing methods):

```python
    def _inc_in_flight(self, instance_id: str) -> None:
        self._in_flight[instance_id] += 1
        self._last_change[instance_id] = time.monotonic()

    def _dec_in_flight(self, instance_id: str) -> None:
        if self._in_flight[instance_id] > 0:
            self._in_flight[instance_id] -= 1
        self._last_change[instance_id] = time.monotonic()

    def in_flight_count(self, instance_id: str) -> int:
        return self._in_flight[instance_id]

    async def wait_for_idle(
        self,
        instance_id: str,
        idle_ms: int = 500,
        timeout_ms: int = 10000,
    ) -> bool:
        """Block until ``in_flight_count == 0`` has held for ``idle_ms`` ms.

        Returns True when settled, False on timeout. ``idle_ms`` defines the
        debounce window so a single momentary zero does not declare success.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        idle_s = idle_ms / 1000.0
        poll = max(0.025, idle_s / 5)
        while time.monotonic() < deadline:
            if self._in_flight[instance_id] == 0:
                if time.monotonic() - self._last_change[instance_id] >= idle_s:
                    return True
            await asyncio.sleep(poll)
        return False
```

Wire the counter into `_on_request` and `_on_response`. Inside `_on_request`, after the `if not _CAPTURE_ALL: ... return` filter block but before the cookie parsing, add:

```python
            self._inc_in_flight(instance_id)
```

Inside `_on_response`, at the top of the `try:` block (before reading `event.request_id`), add:

```python
            self._dec_in_flight(instance_id)
```

Also dec on failure: at the top of `_on_request`, add a `try`/`except` wrapper? No — simpler: also wire `LoadingFailed` and `LoadingFinished`. Add to `setup_interception`, after the existing `tab.add_handler(...ResponseReceived...)` registration:

```python
            def _on_loading_finished(event):
                try:
                    self._dec_in_flight(instance_id)
                except Exception:
                    pass

            def _on_loading_failed(event):
                try:
                    self._dec_in_flight(instance_id)
                except Exception:
                    pass

            tab.add_handler(uc.cdp.network.LoadingFinished, _on_loading_finished)
            tab.add_handler(uc.cdp.network.LoadingFailed, _on_loading_failed)
```

Note: `_on_response` is for `ResponseReceived` (headers arrived) and may fire BEFORE the body completes. We dec on `LoadingFinished` AND `LoadingFailed` because those are the terminal events. To avoid double-dec, REMOVE the `self._dec_in_flight(instance_id)` from `_on_response`. The flow is now: `RequestWillBeSent` increments; `LoadingFinished | LoadingFailed` decrements. `ResponseReceived` is metadata-only.

- [ ] **Step 4: Run tests to verify pass**

```
python -m pytest tests/test_network_idle.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Use `wait_for_idle` in the `navigate` tool**

Edit `src/server.py`. Find the `navigate` tool body (around line 280-310). The current code:

```python
        if wait_until == "domcontentloaded":
            await tab.wait(uc.cdp.page.DomContentEventFired)
        elif wait_until == "networkidle":
            await asyncio.sleep(2)
        else:
            await tab.wait(uc.cdp.page.LoadEventFired)
```

Replace with:

```python
        if wait_until == "domcontentloaded":
            await tab.wait(uc.cdp.page.DomContentEventFired)
        elif wait_until == "networkidle":
            await tab.wait(uc.cdp.page.LoadEventFired)
            settled = await network_interceptor.wait_for_idle(
                instance_id, idle_ms=500, timeout_ms=max(2000, timeout - 1000)
            )
            if not settled:
                debug_logger.log_warning(
                    "server",
                    "navigate",
                    f"network never reached idle within timeout for {url}",
                )
        else:
            await tab.wait(uc.cdp.page.LoadEventFired)
```

Update the docstring for `wait_until` (in the same tool) to:

```python
        wait_until (str): Wait condition. 'load' (default) waits for the
            window onload event. 'domcontentloaded' waits for the DOM ready
            event. 'networkidle' waits for load + a 500ms quiet window with
            zero in-flight requests, bounded by timeout. The earlier 2s sleep
            is gone.
```

- [ ] **Step 6: Run full suite + compile**

```
python -m pytest -v
```
Expected: 51 PASS (48 prior + 3 new).

```
python -m compileall -q src tests
```
Expected: clean.

- [ ] **Step 7: Commit**

```
git add src/network_interceptor.py src/server.py tests/test_network_idle.py
git commit -m "feat(network): real wait_until=networkidle via in-flight counter + LoadingFinished/Failed events"
```

---

## Task 2: `--minimal` flag actually disables sections

**Why:** `server.py:2600-2628` mutates `DISABLED_SECTIONS` inside `if __name__ == "__main__":`, AFTER every `@section_tool(...)` decorator has already run and registered its tool. `--minimal` saves zero registration cost today.

**Files:**
- Modify: `src/server.py` (move section-disable resolution above all tool definitions)

- [ ] **Step 1: Identify the disabled-set source today**

Currently in `src/server.py`:

```python
DISABLED_SECTIONS = set()

def is_section_enabled(section: str) -> bool:
    return section not in DISABLED_SECTIONS

def section_tool(section: str):
    def decorator(func):
        if is_section_enabled(section):
            return mcp.tool(func)
        return func
    return decorator
```

The set is mutated only inside `if __name__ == "__main__":` (line ~2600). To fix: populate the set from environment variables BEFORE any tool definition runs.

- [ ] **Step 2: Read disable set from environment at module top**

Edit `src/server.py`. Replace the existing `DISABLED_SECTIONS = set()` block (near line 47) with:

```python
def _initial_disabled_sections() -> set[str]:
    """Compute the initial disabled-section set before any @section_tool runs.

    Reads MECHCP_DISABLED_SECTIONS (comma-separated section names) and a
    boolean MECHCP_MINIMAL flag. Argparse later in __main__ can still extend
    the set, but the import-time set covers the cold-start optimization
    case where the operator sets the env var in their MCP client config.
    """
    sections: set[str] = set()
    raw = os.environ.get("MECHCP_DISABLED_SECTIONS", "")
    for name in raw.split(","):
        name = name.strip()
        if name:
            sections.add(name)
    if os.environ.get("MECHCP_MINIMAL", "").strip() in {"1", "true", "yes"}:
        sections.update({
            "element-extraction", "file-extraction", "network-debugging",
            "cdp-functions", "progressive-cloning", "cookies-storage",
            "tabs", "debugging", "dynamic-hooks",
        })
    return sections


DISABLED_SECTIONS: set[str] = _initial_disabled_sections()
```

- [ ] **Step 3: Update the argparse main block to add to (not replace) the set**

Find the `if __name__ == "__main__":` block. The existing code looks like:

```python
    if args.minimal:
        DISABLED_SECTIONS.update([...])
    if args.disable_browser_management:
        DISABLED_SECTIONS.add("browser-management")
    ...
```

This is fine because `.update` / `.add` are no-ops if items are already in the set. Leave it.

BUT add right before `mcp.run(...)` a one-liner that prints the **final** disabled set to stderr, so operators can verify their env-var config took effect:

Find:
```python
    if DISABLED_SECTIONS:
        print(f"Disabled tool sections: {', '.join(sorted(DISABLED_SECTIONS))}", file=sys.stderr)
```

It already exists. Good. Add a corresponding `--list-effective` flag? No — too much scope. Leave as is.

- [ ] **Step 4: Write a smoke test that proves the env-var path works**

Create `tests/test_minimal_flag.py`:

```python
"""MECHCP_MINIMAL / MECHCP_DISABLED_SECTIONS take effect before decorator-time."""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


def _reload_server(monkeypatch, **env):
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    sys.modules.pop("server", None)
    return importlib.import_module("server")


@pytest.mark.asyncio
async def test_minimal_env_var_strips_heavy_sections(monkeypatch):
    server = _reload_server(monkeypatch, MECHCP_MINIMAL="1")
    tools = await server.mcp.get_tools()
    names = set(tools.keys())
    # browser-management + element-interaction should remain
    assert "spawn_browser" in names
    # dynamic-hooks should be stripped
    assert "create_dynamic_hook" not in names
    # network-debugging should be stripped
    assert "list_network_requests" not in names


@pytest.mark.asyncio
async def test_disabled_sections_env_var(monkeypatch):
    server = _reload_server(monkeypatch, MECHCP_DISABLED_SECTIONS="dynamic-hooks,debugging")
    tools = await server.mcp.get_tools()
    names = set(tools.keys())
    assert "create_dynamic_hook" not in names
    assert "export_debug_logs" not in names
    assert "navigate" in names  # unaffected
```

- [ ] **Step 5: Run tests to verify**

```
python -m pytest tests/test_minimal_flag.py -v
```
Expected: 2 PASS.

```
python -m pytest -v
```
Expected: 53 PASS.

- [ ] **Step 6: Commit**

```
git add src/server.py tests/test_minimal_flag.py
git commit -m "fix(server): honor MECHCP_MINIMAL/MECHCP_DISABLED_SECTIONS env vars at decorator time"
```

---

## Task 3: Sec-CH-UA client-hints sync when UA is overridden

**Why:** `browser_manager.py:91-94` sets only `user_agent` without `userAgentMetadata`. A spoofed UA claiming Windows while `Sec-CH-UA-Platform` says macOS is an instant Cloudflare bot flag.

**Files:**
- Modify: `src/stealth_scripts.py` (add UA → metadata parser)
- Modify: `src/browser_manager.py` (pass metadata to `set_user_agent_override`)
- Modify: `src/network_interceptor.py` (do the same in `set_user_agent`)
- Create: `tests/test_stealth_scripts.py`

- [ ] **Step 1: Write failing test for the UA parser**

Create `tests/test_stealth_scripts.py`:

```python
"""UA → client-hints metadata parser produces a consistent UA + Sec-CH-UA tuple."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


def test_parse_known_windows_chrome_ua():
    from stealth_scripts import parse_user_agent_metadata

    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    meta = parse_user_agent_metadata(ua)
    assert meta["platform"] == "Windows"
    assert meta["platform_version"].startswith("10")
    assert meta["architecture"] == "x86"
    assert meta["bitness"] == "64"
    assert meta["mobile"] is False
    assert any(b["brand"] == "Google Chrome" and b["version"] == "126" for b in meta["brands"])


def test_parse_known_mac_chrome_ua():
    from stealth_scripts import parse_user_agent_metadata

    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    meta = parse_user_agent_metadata(ua)
    assert meta["platform"] == "macOS"
    assert meta["mobile"] is False


def test_parse_android_chrome_ua_is_mobile():
    from stealth_scripts import parse_user_agent_metadata

    ua = (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
    )
    meta = parse_user_agent_metadata(ua)
    assert meta["platform"] == "Android"
    assert meta["mobile"] is True


def test_parse_unknown_ua_returns_none_for_overrides():
    from stealth_scripts import parse_user_agent_metadata

    meta = parse_user_agent_metadata("CompletelyMadeUpAgent/1.0")
    # Returns None so the caller does NOT attempt set_user_agent_override
    # with metadata (which would mismatch).
    assert meta is None
```

- [ ] **Step 2: Run the test to verify it fails**

```
python -m pytest tests/test_stealth_scripts.py -v
```
Expected: FAIL with `ImportError: cannot import name 'parse_user_agent_metadata'`.

- [ ] **Step 3: Implement the parser**

Append to `src/stealth_scripts.py`:

```python
import re
from typing import Optional


_UA_PLATFORM_PATTERNS = [
    (re.compile(r"\bWindows NT 10\.0"), ("Windows", "10")),
    (re.compile(r"\bWindows NT 11\.0"), ("Windows", "11")),
    (re.compile(r"\bWindows NT 6\.3"), ("Windows", "8.1")),
    (re.compile(r"\bMac OS X (\d+)[_.](\d+)"), ("macOS", None)),
    (re.compile(r"\bAndroid (\d+)"), ("Android", None)),
    (re.compile(r"\bLinux\b"), ("Linux", "")),
    (re.compile(r"\bCrOS\b"), ("Chrome OS", "")),
]

_UA_CHROME_VERSION = re.compile(r"Chrome/(\d+)\.")


def parse_user_agent_metadata(ua: str) -> Optional[dict]:
    """Return a Chrome-compatible userAgentMetadata dict matching ``ua``.

    Returns ``None`` when the UA is not recognized as a Chromium browser —
    callers should then NOT override metadata so the real client-hints
    values continue to ship.
    """
    if not ua or "Chrome/" not in ua:
        return None

    chrome_match = _UA_CHROME_VERSION.search(ua)
    if not chrome_match:
        return None
    major = chrome_match.group(1)

    platform = "Unknown"
    platform_version = ""
    for pattern, (plat, default_ver) in _UA_PLATFORM_PATTERNS:
        m = pattern.search(ua)
        if m:
            platform = plat
            if plat == "macOS" and m.lastindex and m.lastindex >= 2:
                platform_version = f"{m.group(1)}.{m.group(2)}"
            elif plat == "Android" and m.lastindex:
                platform_version = m.group(1)
            else:
                platform_version = default_ver or ""
            break

    mobile = "Mobile" in ua or platform == "Android"
    architecture = "arm" if "arm" in ua.lower() or platform == "Android" else "x86"
    bitness = "64" if ("WOW64" in ua or "Win64" in ua or "x64" in ua or "x86_64" in ua) else "32"

    return {
        "platform": platform,
        "platform_version": platform_version,
        "architecture": architecture,
        "bitness": bitness,
        "model": "",
        "mobile": mobile,
        "brands": [
            {"brand": "Not/A)Brand", "version": "99"},
            {"brand": "Google Chrome", "version": major},
            {"brand": "Chromium", "version": major},
        ],
    }
```

- [ ] **Step 4: Run tests to verify pass**

```
python -m pytest tests/test_stealth_scripts.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Wire the parser into `browser_manager.spawn_browser`**

Edit `src/browser_manager.py`. Find the UA override block:

```python
            if options.user_agent:
                await tab.send(uc.cdp.emulation.set_user_agent_override(
                    user_agent=options.user_agent
                ))
```

Replace with:

```python
            if options.user_agent:
                try:
                    meta = parse_user_agent_metadata(options.user_agent)
                except Exception as exc:
                    debug_logger.log_warning(
                        "browser_manager",
                        "spawn_browser",
                        f"could not parse UA for client-hints: {exc}",
                    )
                    meta = None

                kwargs = {"user_agent": options.user_agent}
                if meta is not None:
                    try:
                        kwargs["user_agent_metadata"] = uc.cdp.emulation.UserAgentMetadata(
                            **{
                                "platform": meta["platform"],
                                "platform_version": meta["platform_version"],
                                "architecture": meta["architecture"],
                                "bitness": meta["bitness"],
                                "model": meta["model"],
                                "mobile": meta["mobile"],
                                "brands": [
                                    uc.cdp.emulation.UserAgentBrandVersion(
                                        brand=b["brand"], version=b["version"]
                                    )
                                    for b in meta["brands"]
                                ],
                            }
                        )
                    except Exception as exc:
                        debug_logger.log_warning(
                            "browser_manager",
                            "spawn_browser",
                            f"could not build UserAgentMetadata: {exc}",
                        )
                await tab.send(uc.cdp.emulation.set_user_agent_override(**kwargs))
```

Add to the existing import block at the top of `browser_manager.py`:

```python
from stealth_scripts import (
    DEFAULT_STEALTH_ARGS,
    STEALTH_INIT_JS,
    parse_user_agent_metadata,
    pick_realistic_viewport,
)
```

- [ ] **Step 6: Mirror in `network_interceptor.set_user_agent`**

Edit `src/network_interceptor.py`. Find:

```python
    async def set_user_agent(self, tab: Tab, user_agent: str):
        """..."""
        try:
            await tab.send(uc.cdp.network.set_user_agent_override(user_agent=user_agent))
            return True
        except Exception as e:
            raise Exception(f"Failed to set user agent: {str(e)}")
```

Replace with:

```python
    async def set_user_agent(self, tab: Tab, user_agent: str):
        """Set custom user agent and matching Sec-CH-UA client hints.

        Pairs the override with a parsed userAgentMetadata so the spoofed UA
        does not collide with real client-hint values, which is a high-signal
        bot fingerprint.
        """
        from stealth_scripts import parse_user_agent_metadata

        try:
            meta = parse_user_agent_metadata(user_agent)
            kwargs = {"user_agent": user_agent}
            if meta is not None:
                from nodriver import cdp as _cdp

                kwargs["user_agent_metadata"] = _cdp.emulation.UserAgentMetadata(
                    platform=meta["platform"],
                    platform_version=meta["platform_version"],
                    architecture=meta["architecture"],
                    bitness=meta["bitness"],
                    model=meta["model"],
                    mobile=meta["mobile"],
                    brands=[
                        _cdp.emulation.UserAgentBrandVersion(
                            brand=b["brand"], version=b["version"]
                        )
                        for b in meta["brands"]
                    ],
                )
                # Network domain wants emulation override; use that path.
                await tab.send(_cdp.emulation.set_user_agent_override(**kwargs))
            else:
                await tab.send(uc.cdp.network.set_user_agent_override(user_agent=user_agent))
            return True
        except Exception as e:
            raise Exception(f"Failed to set user agent: {str(e)}") from e
```

- [ ] **Step 7: Run full suite + compile**

```
python -m pytest -v
python -m compileall -q src tests
```
Expected: 57 PASS.

- [ ] **Step 8: Commit**

```
git add src/stealth_scripts.py src/browser_manager.py src/network_interceptor.py tests/test_stealth_scripts.py
git commit -m "feat(stealth): sync Sec-CH-UA client hints with overridden user agent"
```

---

## Task 4: `navigate` actually attaches the `referrer` argument

**Why:** `server.py:294-298` ignores the `referrer` parameter — it only calls `set_referrer_policy`, never sets the `Referer` header. Every navigation looks like `Sec-Fetch-Site: none`, a classic direct-bot pattern.

**Files:**
- Modify: `src/server.py` (`navigate` tool)

- [ ] **Step 1: Update the navigate body**

In `src/server.py`, locate the `navigate` tool. The relevant section:

```python
    try:
        if referrer:
            await tab.send(uc.cdp.page.set_referrer_policy(
                referrerPolicy='origin-when-cross-origin'
            ))
        await tab.get(url)
```

Replace with:

```python
    try:
        if referrer:
            try:
                await tab.send(
                    uc.cdp.page.navigate(url=url, referrer=referrer)
                )
            except Exception as exc:
                debug_logger.log_warning(
                    "server",
                    "navigate",
                    f"page.navigate with referrer failed, falling back to tab.get: {exc}",
                )
                await tab.send(uc.cdp.network.set_extra_http_headers(
                    headers={"Referer": referrer}
                ))
                await tab.get(url)
        else:
            await tab.get(url)
```

- [ ] **Step 2: Update the docstring**

Find the `referrer (Optional[str])` docstring line in the same tool. Replace:

```python
        referrer (Optional[str]): Referrer URL.
```

with:

```python
        referrer (Optional[str]): If set, attaches as the navigation Referer.
            Adds Sec-Fetch-Site: same-origin / cross-site instead of the
            "no-history" pattern that flags as direct-bot traffic.
```

- [ ] **Step 3: Verify smoke tests still pass**

```
python -m pytest -v
```
Expected: 57 PASS (no test change, but verify no regression).

- [ ] **Step 4: Commit**

```
git add src/server.py
git commit -m "fix(navigate): attach Referer when referrer arg is provided"
```

---

## Task 5: Route `element_cloner` fallback fetches through the tab

**Why:** `element_cloner.py:_fetch_url_text` and `_fetch_asset_metadata` use `requests.get` via `asyncio.to_thread`. Origin sees two parallel JA3 fingerprints (Chrome + Python) from the same IP — trivially correlatable.

**Files:**
- Modify: `src/element_cloner.py`

- [ ] **Step 1: Add a tab-routed fetch helper**

Edit `src/element_cloner.py`. Add a new method to `ElementCloner` (before `_fetch_url_text`):

```python
    async def _fetch_via_tab(self, tab, url: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """Fetch ``url`` inside the page context so the origin sees the page's TLS fingerprint.

        Returns {"status": int, "text": str, "headers": dict} on success, None on failure.
        """
        if not tab:
            return None
        js = (
            "(async () => {"
            "  const r = await fetch(%s, {credentials: 'include', mode: 'cors'});"
            "  const text = await r.text();"
            "  const headers = {};"
            "  r.headers.forEach((v, k) => { headers[k] = v; });"
            "  return {status: r.status, text, headers};"
            "})()"
        ) % json.dumps(url)
        try:
            return await asyncio.wait_for(tab.evaluate(js, await_promise=True), timeout=timeout)
        except Exception as exc:
            debug_logger.log_warning(
                "element_cloner",
                "_fetch_via_tab",
                f"page-context fetch failed for {url}: {exc}",
            )
            return None
```

- [ ] **Step 2: Use tab-routed fetch when a tab is available**

Replace `_fetch_url_text`:

```python
    async def _fetch_url_text(self, url: str, timeout: int = 10, tab=None) -> Optional[Dict[str, Any]]:
        """Fetch a URL and return status/text/headers.

        Prefers the in-page ``fetch`` (so JA3 / cookies match the current
        browsing session). Falls back to Python's ``requests`` if the tab
        rejects the script (e.g. CSP). The fallback is async-safe via
        ``asyncio.to_thread``.
        """
        if tab is not None:
            result = await self._fetch_via_tab(tab, url, timeout=float(timeout))
            if result is not None:
                return result
        try:
            response = await asyncio.to_thread(requests.get, url, timeout=timeout)
            return {"status": response.status_code, "text": response.text, "headers": dict(response.headers)}
        except Exception as exc:
            debug_logger.log_warning(
                "element_cloner",
                "_fetch_url_text",
                f"could not fetch {url}: {exc}",
            )
            return None
```

Replace `_fetch_asset_metadata`:

```python
    async def _fetch_asset_metadata(self, urls: List[str], tab=None) -> Dict[str, Dict[str, Any]]:
        """Fetch asset URLs concurrently. Prefers in-page fetch for stealth."""
        if not urls:
            return {}

        sem = asyncio.Semaphore(8)

        async def fetch_one(url: str) -> tuple[str, Optional[Dict[str, Any]]]:
            async with sem:
                if tab is not None:
                    result = await self._fetch_via_tab(tab, url, timeout=5.0)
                    if result is not None:
                        return url, {
                            "content_type": result.get("headers", {}).get("content-type"),
                            "size": len(result.get("text", "")),
                            "status": result.get("status"),
                        }
                try:
                    response = await asyncio.to_thread(requests.get, url, timeout=5)
                    return url, {
                        "content_type": response.headers.get("content-type"),
                        "size": len(response.content),
                        "status": response.status_code,
                    }
                except Exception as exc:
                    debug_logger.log_warning(
                        "element_cloner",
                        "_fetch_asset_metadata",
                        f"could not fetch asset {url}: {exc}",
                    )
                    return url, None

        results = await asyncio.gather(*(fetch_one(u) for u in urls))
        return {url: meta for url, meta in results if meta is not None}
```

- [ ] **Step 3: Pass `tab` from callers**

Find the call site in `extract_element_assets` (around line 339):

```python
                asset_data['external_assets'] = await self._fetch_asset_metadata(bg_urls)
```

Change to:

```python
                asset_data['external_assets'] = await self._fetch_asset_metadata(bg_urls, tab=tab)
```

Find the call site in `_fetch_and_analyze_files`:

```python
            fetched = await self._fetch_url_text(href, timeout=10)
```

Change to:

```python
            fetched = await self._fetch_url_text(href, timeout=10, tab=tab)
```

And the script-fetch call further down:

```python
            fetched = await self._fetch_url_text(src, timeout=10)
```

Change to:

```python
            fetched = await self._fetch_url_text(src, timeout=10, tab=tab)
```

Also update the `_fetch_and_analyze_files` signature to accept `tab`:

```python
    async def _fetch_and_analyze_files(self, file_data: Dict, base_url: str, max_depth: int, tab=None) -> None:
```

Update its caller in `extract_related_files`:

```python
            if follow_imports and max_depth > 0 and isinstance(file_data, dict):
                await self._fetch_and_analyze_files(file_data, tab.url, max_depth)
```

to:

```python
            if follow_imports and max_depth > 0 and isinstance(file_data, dict):
                await self._fetch_and_analyze_files(file_data, tab.url, max_depth, tab=tab)
```

- [ ] **Step 4: Run pytest**

```
python -m pytest -v
```
Expected: 57 PASS (no test change; just verify nothing breaks).

- [ ] **Step 5: Commit**

```
git add src/element_cloner.py
git commit -m "feat(stealth): route cloner external fetches through the tab to match page JA3 + cookies"
```

---

## Task 6: `wait_for_element` uses MutationObserver push instead of 500ms polling

**Why:** Current loop in `dom_handler.py:495-527` does 60 poll iterations × 2 CDP calls = 120 roundtrips per `wait_for_element` over a 30s timeout. Detector-friendly *and* slow.

**Files:**
- Modify: `src/dom_handler.py`

- [ ] **Step 1: Replace the polling loop with a single awaited promise**

Find the `wait_for_element` method (around line 472-529). Replace its entire body with:

```python
    @staticmethod
    async def wait_for_element(
        tab: Tab,
        selector: str,
        timeout: int = 30000,
        visible: bool = True,
        contains_text: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Wait for ``selector`` to appear (and optionally become visible / contain text).

        Pushes a single MutationObserver into the page that resolves a promise
        when the condition matches. Replaces the prior 500ms polling loop
        (~120 CDP roundtrips per 30s wait) with one Runtime.evaluate.
        """
        text_check = json.dumps(contains_text or "")
        js = (
            "(async () => {"
            "  const sel = %s;"
            "  const wantVisible = %s;"
            "  const wantText = %s;"
            "  const deadline = performance.now() + %d;"
            "  function match(el) {"
            "    if (!el) return null;"
            "    if (wantVisible) {"
            "      const s = window.getComputedStyle(el);"
            "      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return null;"
            "      const r = el.getBoundingClientRect();"
            "      if (r.width === 0 || r.height === 0) return null;"
            "    }"
            "    if (wantText && !(el.innerText || el.textContent || '').includes(wantText)) return null;"
            "    return el;"
            "  }"
            "  function snapshot(el) {"
            "    const r = el.getBoundingClientRect();"
            "    return {"
            "      tag: el.tagName ? el.tagName.toLowerCase() : null,"
            "      id: el.id || null,"
            "      classes: (el.className && el.className.toString && el.className.toString().split(' ')) || [],"
            "      text: (el.innerText || el.textContent || '').slice(0, 200),"
            "      box: {x: r.x, y: r.y, w: r.width, h: r.height},"
            "    };"
            "  }"
            "  return new Promise((resolve) => {"
            "    const found = match(document.querySelector(sel));"
            "    if (found) return resolve(snapshot(found));"
            "    let resolved = false;"
            "    const obs = new MutationObserver(() => {"
            "      if (resolved) return;"
            "      const hit = match(document.querySelector(sel));"
            "      if (hit) { resolved = true; obs.disconnect(); resolve(snapshot(hit)); }"
            "    });"
            "    obs.observe(document.documentElement, {childList: true, subtree: true, attributes: true});"
            "    const tick = () => {"
            "      if (resolved) return;"
            "      if (performance.now() > deadline) { resolved = true; obs.disconnect(); resolve(null); return; }"
            "      const hit = match(document.querySelector(sel));"
            "      if (hit) { resolved = true; obs.disconnect(); resolve(snapshot(hit)); return; }"
            "      setTimeout(tick, 250);"
            "    };"
            "    setTimeout(tick, 250);"
            "  });"
            "})()"
        ) % (json.dumps(selector), "true" if visible else "false", text_check, int(timeout))
        try:
            result = await tab.evaluate(js, await_promise=True)
            return result
        except Exception as exc:
            debug_logger.log_error("dom_handler", "wait_for_element", exc)
            return None
```

Add `import json` at the top of `dom_handler.py` if it's not already there.

- [ ] **Step 2: Run pytest**

```
python -m pytest -v
```
Expected: 57 PASS.

- [ ] **Step 3: Quick live verification**

Modify `tests/manual_clone_smoke.py` temporarily? No — keep it as a separate test command. Add a one-liner verification:

Run from PowerShell or bash:
```
python -c "import asyncio,sys; sys.path.insert(0,'src');
from browser_manager import BrowserManager; from dom_handler import DOMHandler
from models import BrowserOptions
async def main():
    bm = BrowserManager()
    inst = await bm.spawn_browser(BrowserOptions(headless=True, viewport_width=1366, viewport_height=768))
    tab = await bm.get_tab(inst.instance_id)
    await tab.get('https://example.com')
    found = await DOMHandler.wait_for_element(tab, 'h1', timeout=5000)
    print('found:', bool(found), found.get('text') if found else None)
    await bm.close_instance(inst.instance_id)
asyncio.run(main())"
```
Expected: prints `found: True` and the `h1` text from example.com.

- [ ] **Step 4: Commit**

```
git add src/dom_handler.py
git commit -m "perf(dom): replace wait_for_element 500ms poll with MutationObserver-based push"
```

---

## Task 7: `click_element` returns post-state verification

**Why:** Today `click_element` returns bare `True` whether or not anything actually happened. Agents click on covered buttons and never know.

**Files:**
- Modify: `src/dom_handler.py` (`click_element`)
- Modify: `src/server.py` (`click_element` tool — propagate the dict)

- [ ] **Step 1: Replace the click method's return shape**

Find `click_element` in `src/dom_handler.py` (around line 166). Replace its body:

```python
    @staticmethod
    async def click_element(
        tab: Tab,
        selector: str,
        button: str = "left",
        click_count: int = 1,
    ) -> Dict[str, Any]:
        """Click an element, returning a structured before/after state report.

        Returns ``{success, navigated, dom_mutated, url_before, url_after,
        outer_html_hash_before, outer_html_hash_after, error}``. Agents can
        check ``navigated`` or ``dom_mutated`` to verify the click had an
        effect (vs. silently hitting a covering overlay).
        """
        import hashlib

        def _hash_dom(html: str) -> str:
            return hashlib.blake2b(html.encode("utf-8", "ignore"), digest_size=8).hexdigest()

        try:
            url_before = getattr(tab, "url", "")
            try:
                outer_before = await tab.evaluate("document.documentElement.outerHTML.slice(0, 200000)")
                outer_before = outer_before if isinstance(outer_before, str) else ""
            except Exception:
                outer_before = ""
            hash_before = _hash_dom(outer_before)

            element = await tab.select(selector)
            if not element:
                return {
                    "success": False,
                    "navigated": False,
                    "dom_mutated": False,
                    "error": f"Element not found: {selector}",
                }

            await element.scroll_into_view()
            await asyncio.sleep(0.2)
            await element.click()
            await asyncio.sleep(0.4)

            url_after = await tab.evaluate("window.location.href")
            try:
                outer_after = await tab.evaluate("document.documentElement.outerHTML.slice(0, 200000)")
                outer_after = outer_after if isinstance(outer_after, str) else ""
            except Exception:
                outer_after = ""
            hash_after = _hash_dom(outer_after)

            return {
                "success": True,
                "navigated": isinstance(url_after, str) and url_after != url_before,
                "dom_mutated": hash_after != hash_before,
                "url_before": url_before,
                "url_after": url_after if isinstance(url_after, str) else None,
                "outer_html_hash_before": hash_before,
                "outer_html_hash_after": hash_after,
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "navigated": False,
                "dom_mutated": False,
                "error": str(e),
            }
```

- [ ] **Step 2: Update the `click_element` MCP tool wrapper in `server.py`**

Find the `click_element` tool in `src/server.py` (around line 408). Its current signature returns `bool`. Update:

```python
@section_tool("element-interaction")
async def click_element(
    instance_id: str,
    selector: str,
    button: str = "left",
    click_count: int = 1
) -> Dict[str, Any]:
    """Click an element and return a post-state verification report.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector of the element to click.
        button (str): Mouse button ('left', 'right', 'middle').
        click_count (int): Number of clicks (use 2 for double-click).

    Returns:
        Dict[str, Any]: ``{success, navigated, dom_mutated, url_before,
        url_after, error}``. ``success`` means the click was dispatched;
        ``navigated`` and ``dom_mutated`` show whether anything actually
        changed (the click may have hit an overlay).
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"success": False, "navigated": False, "dom_mutated": False,
                "error": f"Instance not found: {instance_id}"}
    return await dom_handler.click_element(tab, selector, button=button, click_count=click_count)
```

- [ ] **Step 3: Update `tests/test_tool_registration.py` to expect `click_element` (unchanged signature in the test)**

The test only checks names, not return types. No change required. Run:

```
python -m pytest -v
```
Expected: 57 PASS.

- [ ] **Step 4: Commit**

```
git add src/dom_handler.py src/server.py
git commit -m "feat(dom): click_element returns navigated/dom_mutated post-state verification"
```

---

## Task 8: Lightweight page-text tools (`get_visible_text`, `get_page_outline`)

**Why:** Agents currently call `get_page_content` and get the full HTML (token grenade) or `take_screenshot` (also expensive). Two cheap text-projection tools cover 80% of the "what's on the page" intent.

**Files:**
- Modify: `src/server.py` (add two tools)

- [ ] **Step 1: Add `get_visible_text` tool**

In `src/server.py`, find the existing `get_page_content` tool. Right after it (or in the same section), add:

```python
@section_tool("element-interaction")
async def get_visible_text(
    instance_id: str,
    max_chars: int = 4000,
) -> Dict[str, Any]:
    """Return the page's visible innerText, truncated to ``max_chars``.

    Cheap alternative to ``get_page_content`` (which dumps full HTML) and to
    ``take_screenshot`` (which costs tokens to look at). Use this when the
    agent only needs to know "what does the page say".

    Args:
        instance_id (str): Browser instance ID.
        max_chars (int): Hard cap on returned text length (default 4000).

    Returns:
        Dict[str, Any]: ``{url, title, text, truncated}``.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"url": "", "title": "", "text": "", "truncated": False,
                "error": f"Instance not found: {instance_id}"}
    try:
        url = getattr(tab, "url", "")
        title = await tab.evaluate("document.title")
        text = await tab.evaluate(
            "document.body && document.body.innerText ? document.body.innerText : ''"
        )
        if not isinstance(text, str):
            text = ""
        truncated = len(text) > max_chars
        return {
            "url": url,
            "title": title if isinstance(title, str) else "",
            "text": text[:max_chars],
            "truncated": truncated,
            "total_length": len(text),
        }
    except Exception as e:
        return {"url": "", "title": "", "text": "", "truncated": False, "error": str(e)}


@section_tool("element-interaction")
async def get_page_outline(
    instance_id: str,
) -> Dict[str, Any]:
    """Return a compact outline of headings, landmarks, forms, buttons and links.

    Designed for an agent that needs to navigate or summarize without dumping
    the entire DOM. Returns at most ~200 items across all categories.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        Dict[str, Any]: ``{url, title, headings, landmarks, forms, buttons, links}``.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"error": f"Instance not found: {instance_id}"}
    js = """(() => {
      const lim = (arr, n) => arr.slice(0, n);
      const txt = (el) => ((el.innerText || el.textContent || '').trim().slice(0, 120));
      const headings = lim(
        [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')]
          .filter(h => txt(h))
          .map(h => ({level: parseInt(h.tagName[1]), text: txt(h)})),
        80,
      );
      const landmarks = lim(
        [...document.querySelectorAll('main, nav, header, footer, aside, [role=main], [role=navigation], [role=banner]')]
          .map(el => ({tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || null, label: el.getAttribute('aria-label') || null, id: el.id || null})),
        30,
      );
      const forms = lim(
        [...document.querySelectorAll('form')]
          .map(f => ({action: f.getAttribute('action') || null, method: (f.getAttribute('method') || 'get').toLowerCase(), id: f.id || null, fields: [...f.querySelectorAll('input, select, textarea')].slice(0, 20).map(i => ({name: i.name || null, type: i.type || i.tagName.toLowerCase(), required: i.required, label: (i.labels && i.labels[0] && txt(i.labels[0])) || null}))})),
        15,
      );
      const buttons = lim(
        [...document.querySelectorAll('button, [role=button], input[type=submit], input[type=button]')]
          .map(b => ({text: txt(b) || b.value || null, id: b.id || null, disabled: b.disabled || false})),
        40,
      );
      const links = lim(
        [...document.querySelectorAll('a[href]')]
          .filter(a => txt(a))
          .map(a => ({text: txt(a), href: a.href})),
        50,
      );
      return {
        url: window.location.href,
        title: document.title,
        headings, landmarks, forms, buttons, links,
      };
    })()"""
    try:
        result = await tab.evaluate(js)
        return result if isinstance(result, dict) else {"error": "evaluate returned non-dict"}
    except Exception as e:
        return {"error": str(e)}
```

- [ ] **Step 2: Run smoke tests**

```
python -m pytest -v
```
Expected: 57 PASS (no test for the new tools — they're additive).

- [ ] **Step 3: Commit**

```
git add src/server.py
git commit -m "feat(tools): add get_visible_text and get_page_outline for token-efficient page reading"
```

---

## Task 9: `screenshot_element` and `get_console_logs` tools

**Why:** Two final agent-UX additions that close common workflows: validate a UI state cheaply, and surface JS errors the page produced.

**Files:**
- Modify: `src/server.py`

- [ ] **Step 1: Add `screenshot_element` tool**

In `src/server.py`, near the existing `take_screenshot` tool, add:

```python
@section_tool("element-interaction")
async def screenshot_element(
    instance_id: str,
    selector: str,
    padding_px: int = 8,
    file_path: Optional[str] = None,
) -> Union[str, Dict[str, Any]]:
    """Screenshot a single element instead of the whole viewport.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector of the target element.
        padding_px (int): Pixels of margin around the element in the capture.
        file_path (Optional[str]): If provided, write the PNG to this path
            (sandbox-resolved). Returns the resolved path. Otherwise returns
            base64-encoded PNG.

    Returns:
        Union[str, Dict[str, Any]]: Path string or base64 data on success;
        ``{success: False, error}`` on failure.
    """
    import base64 as _b64

    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"success": False, "error": f"Instance not found: {instance_id}"}

    js = (
        "(() => { const el = document.querySelector(%s);"
        " if (!el) return null;"
        " const r = el.getBoundingClientRect();"
        " return {x: r.x, y: r.y, width: r.width, height: r.height,"
        " dpr: window.devicePixelRatio || 1}; })()"
    ) % json.dumps(selector)
    try:
        box = await tab.evaluate(js)
    except Exception as exc:
        return {"success": False, "error": f"could not locate element: {exc}"}
    if not isinstance(box, dict):
        return {"success": False, "error": f"element not found: {selector}"}

    pad = max(0, int(padding_px))
    clip = {
        "x": max(0.0, float(box["x"]) - pad),
        "y": max(0.0, float(box["y"]) - pad),
        "width": float(box["width"]) + 2 * pad,
        "height": float(box["height"]) + 2 * pad,
        "scale": 1.0,
    }
    try:
        png_b64 = await tab.send(
            uc.cdp.page.capture_screenshot(format_="png", clip=uc.cdp.page.Viewport(**clip))
        )
    except Exception as exc:
        return {"success": False, "error": f"capture_screenshot failed: {exc}"}

    if isinstance(png_b64, tuple):
        png_b64 = png_b64[0]
    if not isinstance(png_b64, str):
        return {"success": False, "error": "capture_screenshot returned no data"}

    if file_path:
        try:
            target = safe_join(file_path, allowed_suffixes={".png"})
        except ValueError as exc:
            return {"success": False, "error": f"unsafe file_path rejected: {exc}"}
        target.write_bytes(_b64.b64decode(png_b64))
        return str(target)
    return png_b64
```

- [ ] **Step 2: Add `get_console_logs` tool**

`browser_manager` already records console messages on the instance metadata. Verify with a quick `Grep -n "console" src/browser_manager.py`. If the per-instance console buffer doesn't exist yet, add minimal capture wiring.

For this task, assume we need to add it. Edit `src/browser_manager.py`. In `__init__`, no change needed (we'll store on the existing `self._instances[instance_id]` dict). Add a console hook in `spawn_browser`, after the `Network.enable` wiring is done by the network interceptor (the simplest place is in `_setup_dynamic_hooks`'s same neighborhood — but to keep `_setup_dynamic_hooks` focused, add a new method):

After `_setup_dynamic_hooks` add:

```python
    async def _setup_console_capture(self, tab: Tab, instance_id: str) -> None:
        """Capture page console messages into the per-instance buffer."""
        buf: List[Dict[str, Any]] = []
        async with self._lock:
            inst = self._instances.get(instance_id)
            if inst is not None:
                inst.setdefault("console_logs", buf)
                buf = inst["console_logs"]

        def _on_console(event):
            try:
                buf.append({
                    "timestamp": datetime.now().isoformat(),
                    "level": getattr(event, "type_", "log"),
                    "text": " ".join(
                        str(getattr(a, "value", a)) for a in getattr(event, "args", [])
                    ) or str(event),
                })
                if len(buf) > 500:
                    del buf[: len(buf) - 500]
            except Exception:
                pass

        try:
            await tab.send(uc.cdp.runtime.enable())
            tab.add_handler(uc.cdp.runtime.ConsoleAPICalled, _on_console)
        except Exception as exc:
            debug_logger.log_warning(
                "browser_manager",
                "_setup_console_capture",
                f"console capture failed: {exc}",
            )
```

Call it from `spawn_browser` right after `_setup_dynamic_hooks`:

```python
            await self._setup_dynamic_hooks(tab, instance_id)
            await self._setup_console_capture(tab, instance_id)
```

Now add the tool in `src/server.py`:

```python
@section_tool("debugging")
async def get_console_logs(
    instance_id: str,
    since_index: int = 0,
    level_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Return browser console messages captured since spawn.

    Args:
        instance_id (str): Browser instance ID.
        since_index (int): Return entries at index >= this value (the agent
            can poll incrementally).
        level_filter (Optional[str]): If set, only return entries whose level
            matches (e.g. 'error', 'warning').

    Returns:
        Dict[str, Any]: ``{instance_id, total, returned, entries: [...], next_index}``.
    """
    async with browser_manager._lock:
        inst = browser_manager._instances.get(instance_id)
        if inst is None:
            return {"error": f"Instance not found: {instance_id}"}
        logs = list(inst.get("console_logs", []))

    if level_filter:
        logs = [e for e in logs if str(e.get("level", "")).lower() == level_filter.lower()]
    slice_start = max(0, int(since_index))
    entries = logs[slice_start:]
    return {
        "instance_id": instance_id,
        "total": len(logs),
        "returned": len(entries),
        "next_index": len(logs),
        "entries": entries[-200:],
    }
```

- [ ] **Step 3: Run pytest**

```
python -m pytest -v
```
Expected: 57 PASS.

- [ ] **Step 4: Commit**

```
git add src/server.py src/browser_manager.py
git commit -m "feat(tools): add screenshot_element and get_console_logs"
```

---

## Task 10: Bezier mouse trajectory for `click_element`

**Why:** A click with no preceding pointer movement is detector-flagged. Adding a short 4-8 hop Bezier path between the current pointer position and the target removes the most basic "click without trajectory" pattern.

**Files:**
- Modify: `src/stealth_scripts.py` (add Bezier helper)
- Modify: `src/dom_handler.py` (`click_element` calls the helper)

- [ ] **Step 1: Add the Bezier helper**

Append to `src/stealth_scripts.py`:

```python
import math
from typing import List, Tuple


def bezier_path(
    start: Tuple[float, float],
    end: Tuple[float, float],
    *,
    steps: int = 12,
    jitter: float = 18.0,
    rng: random.Random | None = None,
) -> List[Tuple[float, float, float]]:
    """Return a list of (x, y, dwell_seconds) along a jittered cubic Bezier.

    ``dwell_seconds`` is a small Gaussian-jittered pause between hops so the
    overall trajectory has organic variance instead of a constant frame rate.
    """
    r = rng or random
    cx1 = start[0] + (end[0] - start[0]) * 0.33 + r.uniform(-jitter, jitter)
    cy1 = start[1] + (end[1] - start[1]) * 0.33 + r.uniform(-jitter, jitter)
    cx2 = start[0] + (end[0] - start[0]) * 0.66 + r.uniform(-jitter, jitter)
    cy2 = start[1] + (end[1] - start[1]) * 0.66 + r.uniform(-jitter, jitter)

    path: List[Tuple[float, float, float]] = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1.0 - t
        x = (mt ** 3) * start[0] + 3 * (mt ** 2) * t * cx1 + 3 * mt * (t ** 2) * cx2 + (t ** 3) * end[0]
        y = (mt ** 3) * start[1] + 3 * (mt ** 2) * t * cy1 + 3 * mt * (t ** 2) * cy2 + (t ** 3) * end[1]
        dwell = max(0.005, r.gauss(0.018, 0.006))
        path.append((x, y, dwell))
    return path
```

- [ ] **Step 2: Use the path before the actual click**

Edit `src/dom_handler.py` `click_element`. Inside its try block, AFTER `await element.scroll_into_view()` and BEFORE `await element.click()`, add:

```python
            try:
                from stealth_scripts import bezier_path
                from nodriver import cdp as _cdp

                box = await tab.evaluate(
                    f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
                    " if (!el) return null;"
                    " const r = el.getBoundingClientRect();"
                    " return {x: r.x + r.width/2, y: r.y + r.height/2}; }})()"
                )
                if isinstance(box, dict) and "x" in box and "y" in box:
                    start = (max(0.0, float(box["x"]) - 200.0), max(0.0, float(box["y"]) - 80.0))
                    for x, y, dwell in bezier_path(start, (float(box["x"]), float(box["y"]))):
                        await tab.send(
                            _cdp.input_.dispatch_mouse_event(
                                type_="mouseMoved", x=x, y=y, button="none",
                            )
                        )
                        await asyncio.sleep(dwell)
            except Exception as exc:
                debug_logger.log_warning(
                    "dom_handler",
                    "click_element",
                    f"mouse trajectory failed (continuing with direct click): {exc}",
                )
```

Add `import json` and `import asyncio` at the top of `dom_handler.py` if not already present. (Asyncio is already imported.)

- [ ] **Step 3: Run pytest**

```
python -m pytest -v
```
Expected: 57 PASS.

- [ ] **Step 4: Commit**

```
git add src/stealth_scripts.py src/dom_handler.py
git commit -m "feat(stealth): jittered Bezier mouse trajectory before click_element dispatch"
```

---

## Task 11: `block_resources` docstring + warning

**Why:** Today the docstring example shows `['image', 'font', 'stylesheet']`, which is the most bot-like configuration. An agent reading the schema will copy the example verbatim.

**Files:**
- Modify: `src/server.py` (`spawn_browser` docstring + a warning log in `network_interceptor`)
- Modify: `src/network_interceptor.py`

- [ ] **Step 1: Update the docstring**

In `src/server.py`, find the `spawn_browser` tool. Update the `block_resources` line in its docstring:

```python
        block_resources (List[str]): Resource types or URL patterns to block.
            DO NOT block image/font/stylesheet for stealth-sensitive
            navigation: zero image bytes per page is itself a strong bot
            signal. Prefer specific URL patterns (e.g. ``['*googletagmanager.com*']``)
            over coarse resource-type bans.
```

- [ ] **Step 2: Warn at setup time when image/font/stylesheet are blocked**

In `src/network_interceptor.py` `setup_interception`, near the start of the `if block_resources:` block, add:

```python
                _NOISY_STEALTH = {"image", "font", "stylesheet"}
                noisy = [r for r in block_resources if r.lower() in _NOISY_STEALTH]
                if noisy:
                    debug_logger.log_warning(
                        "network_interceptor",
                        "setup_interception",
                        f"blocking {noisy} is a strong bot fingerprint; prefer URL patterns",
                    )
```

- [ ] **Step 3: Run pytest + commit**

```
python -m pytest -v
git add src/server.py src/network_interceptor.py
git commit -m "docs(stealth): warn when block_resources includes image/font/stylesheet"
```

---

## Final verification

After all 11 tasks land:

- [ ] **Run the full pytest suite:**

```
python -m pytest -v 2>&1 | tail -5
```
Expected: `57 passed` (48 prior + 3 network_idle + 4 stealth-scripts + 2 minimal-flag).

- [ ] **Run the live clone smoke against frontiersin.org:**

```
python tests/manual_clone_smoke.py 2>&1 | tail -15
```
Expected: clone succeeds, file written, capture count similar to before (~70-90 requests), NO new error messages.

- [ ] **Compile-check:**

```
python -m compileall -q src tests
```
Expected: clean.

- [ ] **Push:**

```
git push
```

---

## Self-review notes

- **Spec coverage:** Sprint focuses on Stealth MED + Perf HIGH + UX HIGH from `sprint.md`. Tasks 1, 7, 8, 9 close UX HIGH. Tasks 3, 4, 5, 10, 11 close Stealth MED. Tasks 2, 6 close Perf HIGH. Iframe entry and Shadow DOM are intentionally deferred (noted in plan header).
- **Placeholders:** No "TBD" / "TODO" / "add validation" patterns. Every code block contains the actual change.
- **Type consistency:** `NetworkInterceptor._in_flight` is `Dict[str, int]` everywhere; `click_element` returns a dict (consistent across `dom_handler.py` and `server.py` wrapper); `parse_user_agent_metadata` returns `Optional[dict]` and every caller checks for None.
- **Test naming:** Each test file matches its target (`test_network_idle.py`, `test_stealth_scripts.py`, `test_minimal_flag.py`). Existing fixtures (`src_on_path`, autouse `_sandbox_env`) are reused.
- **Commit cadence:** Each task ends in its own commit so a bad task can be reverted without affecting others.
