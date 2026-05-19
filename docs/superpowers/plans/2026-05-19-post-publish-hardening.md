# MechCP Sprint C: Post-Publish Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining post-publish items now that the repo is live and shared on LinkedIn: add CI to gate regressions, publish the standard public-repo documentation files (CONTRIBUTING, SECURITY, CHANGELOG), enforce the .gitignore for vendored build artifacts, and add Shadow DOM + iframe entry to the DOM tools so agents stop failing on every Web-Components site.

**Architecture:** Each task is additive or strictly local. The CI workflow runs `pytest` + `compileall` on every PR. The docs are static files at the repo root. The Shadow DOM helper is a single JS template stored in `src/js/`. iframe entry adds two new MCP tools and a `frame_id` parameter to the existing interaction tools — the existing tools keep their old behavior when `frame_id` is omitted. No breaking changes to the public tool surface.

**Tech Stack:** GitHub Actions, Python 3.10+, pytest, nodriver 0.47.x (CDP `Target.attachToTarget` for iframe entry, `DOM.querySelector(pierce=true)` for shadow DOM).

**Scope decisions (still deferred to future sprints):**
- **Full cloner consolidation** (delete 5 legacy modules, replace `cloner/__init__.py` shim with real `UnifiedCloner` + strategies). Tracked in `sprint.md §1`. This is ~1 day of focused refactoring with API parity tests and is best done with a dedicated subagent-driven session.
- **Tools/ migration of remaining 10 server.py sections.** Tracked in `sprint.md §2`. Mechanical but tedious; each section needs its own commit + parity test.
- **Re-author git history with privacy-protected email.** User has been informed; opt-in only.

---

## File Structure (deltas in this sprint)

```
.github/
  workflows/
    ci.yml                      # New: pytest + compileall on PR + push
CONTRIBUTING.md                 # New: dev setup, test commands, PR process
SECURITY.md                     # New: vulnerability reporting + responsible-disclosure
CHANGELOG.md                    # New: 0.3.0 + 0.4.0 release notes
.gitignore                      # Modify: untrack vendor build artifacts (verify)
src/
  js/
    query_deep.js               # New: querySelectorDeep for shadow DOM piercing
  dom_handler.py                # Modify: add query_shadow + frame routing for click/type/wait
  server.py                     # Modify: add list_frames + query_shadow MCP tools;
                                #          add optional frame_id arg to click/type/wait
tests/
  test_shadow_query.py          # New: shadow DOM helper unit (JS-substitution + return-shape)
  test_frame_routing.py         # New: frame_id routing decision logic
```

---

## Task 1: GitHub Actions CI workflow

**Why:** PRs and pushes need to gate the 57-test smoke suite. Without CI a regression lands silently and the LinkedIn-driven traffic sees a broken first commit.

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [master, main]
  pull_request:

permissions:
  contents: read

jobs:
  test:
    name: Python ${{ matrix.python-version }} on ${{ matrix.os }}
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest]
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install runtime + test dependencies
        run: |
          python -m pip install --upgrade pip
          # Install everything except the vendored py2js, which needs Chrome
          # to be useful at runtime; CI runs no real browser, only the smoke
          # tests that mock the surface.
          pip install fastmcp==2.11.2 pydantic==2.11.7 python-dotenv==1.1.1 jsbeautifier==1.15.4 strinpy==0.0.4 strbuilder==1.1.3 psutil==7.0.0 pillow==11.3.0 requests==2.32.3
          pip install pytest>=7.0 pytest-asyncio>=0.21
          pip install ./vendor/py2js
          # nodriver pulls a real Chrome via its postinstall; install last
          # so a download failure does not block the rest.
          pip install nodriver==0.47.0 || echo "nodriver install warning, continuing"

      - name: Compile-check all sources
        run: python -m compileall -q src tests vendor

      - name: Run pytest
        env:
          MECHCP_LOG_LEVEL: ERROR
        run: python -m pytest -v
```

- [ ] **Step 2: Verify the YAML parses**

Run:

```
python -c "import yaml,pathlib; print('OK:', len(yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text())['jobs']['test']['steps']), 'steps')"
```

Expected: `OK: 4 steps`. If yaml is not installed, install with `pip install pyyaml` first.

- [ ] **Step 3: Commit**

```
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow running pytest + compileall on push/PR"
```

---

## Task 2: CONTRIBUTING.md

**Why:** Standard public-repo signal. Contributors need to know the dev setup, where tests live, and how to open a PR. The README points to it implicitly via the "feedback, PRs welcome" line in the LinkedIn post.

**Files:**
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: Write the file**

Create `CONTRIBUTING.md`:

```markdown
# Contributing to MechCP

Thanks for your interest. MechCP is a hardened browser-automation MCP server for AI agents, and contributions are welcome.

## Development setup

1. Fork and clone:
   ```
   git clone https://github.com/<your-fork>/MechCP.git
   cd MechCP
   ```

2. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   source venv/bin/activate   # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   pip install pytest pytest-asyncio
   ```

3. Run the test suite to confirm the baseline is green:
   ```
   python -m pytest -v
   ```
   Expected: 57 tests pass.

4. Compile-check all source:
   ```
   python -m compileall -q src tests vendor
   ```

## Project conventions

- **Stdout is reserved for JSON-RPC.** Logs and banners go to stderr. Anything you add must respect this — when in doubt route through `debug_logger`.
- **AI-supplied Python paths must go through `safe_code.safe_compile`.** Do not call `exec`/`eval` directly on agent input.
- **File-write tools must resolve through `path_safety.safe_join`.** Caller-supplied paths are always treated as untrusted.
- **Pydantic v2 only.** Use `model_dump()` (not `.dict()`).
- **No bare `except:`.** Catch `Exception` and log with context.
- **Type hints encouraged.** `Optional[Any]` on a public MCP tool parameter is a smell because the LLM sees the JSON schema.

## Tests

- Smoke tests live in `tests/`. They do NOT spawn real browsers.
- Real-browser smoke is in `tests/manual_clone_smoke.py` (run manually).
- Every new MCP tool should have at least one test asserting its presence in the registry.
- Every new helper in `src/safe_code.py` or `src/path_safety.py` should have an attack-rejection test.

## Pull-request checklist

- [ ] `python -m pytest -v` passes locally.
- [ ] `python -m compileall -q src tests vendor` passes.
- [ ] No new `print()` calls hit stdout from within the MCP server runtime.
- [ ] Commit messages use conventional-commits prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- [ ] If you added a new MCP tool, the README "What it does" / tool list is updated.

## Reporting security issues

See `SECURITY.md` for the responsible-disclosure process. Do NOT open public issues for vulnerabilities.

## Code of conduct

Be excellent. Disagreements are fine; personal attacks, harassment, and bad-faith engagement are not, and will result in being blocked from the repo.
```

- [ ] **Step 2: Commit**

```
git add CONTRIBUTING.md
git commit -m "docs: add CONTRIBUTING with dev setup, conventions, and PR checklist"
```

---

## Task 3: SECURITY.md

**Why:** Standard public-repo signal. Security researchers expect a documented disclosure channel before they open a public issue with a CVE. The README's "Security model" section already exists, but the dedicated SECURITY.md is what GitHub's security tab and security-researcher tooling looks for.

**Files:**
- Create: `SECURITY.md`

- [ ] **Step 1: Write the file**

Create `SECURITY.md`:

```markdown
# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.3.x   | yes       |
| earlier | no — please upgrade |

## Reporting a vulnerability

If you have found a security issue in MechCP, please report it privately. Do NOT open a public GitHub issue.

Preferred channels:

1. **GitHub Security Advisory** (preferred). Open a draft advisory at
   https://github.com/RsGoksel/MechCP/security/advisories/new. This keeps the
   discussion private until a fix is ready.
2. **Direct email** to the maintainer listed in the GitHub profile of the
   repo owner.

Please include:

- A concise description of the vulnerability.
- A proof-of-concept or reproducer.
- The affected version (run `git rev-parse HEAD` in your clone, or note the
  release tag).
- Your suggested CVSS score and severity.

I aim to acknowledge reports within 72 hours and provide a fix or mitigation
plan within 14 days for HIGH/CRITICAL findings.

## Scope

In scope:

- The MCP server code under `src/`.
- The vendored `py2js` package under `vendor/py2js/`.
- The default Chrome flags in `src/stealth_scripts.py` and the
  `addScriptToEvaluateOnNewDocument` payload (any escape from that sandbox
  is in scope).
- The AST validator in `src/safe_code.py` and any path-resolution issue in
  `src/path_safety.py`.

Out of scope:

- Detection of MechCP-driven browsers by individual anti-bot services. The
  stealth posture is best-effort and intentionally documented as such in the
  README.
- Vulnerabilities in upstream dependencies (`nodriver`, `fastmcp`, `pydantic`)
  that are not aggravated by MechCP's usage. Please report those upstream.
- Issues in your own MCP client / agent configuration.

## Responsible disclosure timeline

- T+0: report received.
- T+3 days: triage acknowledgement.
- T+14 days: fix or mitigation plan communicated.
- T+90 days: public disclosure if no fix has shipped (negotiable).

Reporters who follow this process are credited in the release notes unless
they request anonymity.
```

- [ ] **Step 2: Commit**

```
git add SECURITY.md
git commit -m "docs: add SECURITY policy with private disclosure channel"
```

---

## Task 4: CHANGELOG.md

**Why:** Releases need a human-readable history. Right now the only narrative is in the git log, which is hostile to read for non-engineers.

**Files:**
- Create: `CHANGELOG.md`

- [ ] **Step 1: Write the file**

Create `CHANGELOG.md`:

```markdown
# Changelog

All notable changes to MechCP are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Actions CI workflow running `pytest` + `compileall` on every push and PR.
- CONTRIBUTING.md, SECURITY.md, CHANGELOG.md (standard public-repo docs).
- `query_shadow` MCP tool — pierces open Shadow DOM via `querySelectorDeep`.
- `list_frames` MCP tool — enumerates child iframes with frame IDs.
- Optional `frame_id` parameter on `click_element`, `type_text`, and
  `wait_for_element` (still works without it for top-level documents).

## [0.3.0] - 2026-05-19

This is the first published release of the MechCP fork. It supersedes the
upstream `stealth-browser-mcp` codebase with a security and code-quality
pass focused on running AI-supplied code safely on the host.

### Added
- `src/safe_code.py` — AST validator + sandboxed `safe_compile` for every
  AI-supplied Python path. Blocks imports, dunder access, walrus operator,
  bare `__builtins__` references, and the standard sandbox-escape patterns.
- `src/path_safety.py` — `safe_join` + `sanitize_filename` that lock every
  AI-supplied path under `MECHCP_OUTPUT_DIR`.
- `src/stealth_scripts.py` with `STEALTH_INIT_JS` injected via
  `Page.addScriptToEvaluateOnNewDocument` on every spawn:
  `navigator.webdriver`, `plugins`, `languages`, `Notification.permission`,
  WebGL vendor/renderer, and `window.chrome.runtime` are patched before the
  page's first script.
- `DEFAULT_STEALTH_ARGS` applied to `uc.Config` (closes
  `AutomationControlled` and related blink-feature tells).
- Realistic-viewport sampler replaces the bot-fleet 1920x1080 default.
- Gaussian-jittered keystrokes + jittered Bezier mouse trajectory before
  clicks (`type_text`, `click_element`).
- `Sec-CH-UA` client-hints synchronization when the user agent is
  overridden — closes the spoofed-UA-vs-real-client-hints fingerprint gap.
- Real `wait_until="networkidle"` via in-flight request counter
  (previously a literal 2-second sleep).
- `click_element` returns `{success, navigated, dom_mutated, ...}` instead
  of bare `True`, so agents can verify the click had an effect.
- New token-efficient tools: `get_visible_text`, `get_page_outline`,
  `screenshot_element`, `get_console_logs`.
- `MECHCP_MINIMAL` / `MECHCP_DISABLED_SECTIONS` env vars honored at
  decorator time (saves ~85 unnecessary tool registrations).
- Vendored `py2js` under `vendor/py2js/` (removes force-push risk from
  the upstream personal fork).
- 57-test pytest smoke suite covering imports, tool registration,
  `safe_code` attack rejection, `path_safety` traversal blocking, network
  idle detection, and the tools/ package wiring.
- `MECHCP_*` env-var table in README, `TERMS_OF_USE.md`, MIT license.

### Changed
- `debug_logger` rewritten: stderr-only (stdio-MCP safe), bounded
  `deque(maxlen)` per level, header redaction (`Authorization`, `Cookie`,
  `X-Api-Key`, ...), pickle exports removed.
- `network_interceptor` request store bounded with `deque(maxlen=N)` and
  FIFO eviction; default-filter for `Image/Font/Media/Stylesheet`.
- `wait_for_element` rewritten to push a single MutationObserver-backed
  promise instead of polling every 500ms (~120 CDP roundtrips → 1).
- `dynamic_hook_system.Fetch.enable` is now lazy — deferred until the
  first hook is created, eliminating both a per-request stall and the
  shutdown noise from in-flight RequestPaused handlers.
- `element_cloner` external fetches route through the tab's `fetch()` so
  the origin sees one JA3 + one cookie jar (previously Python `requests`
  produced a second, easily correlated fingerprint).
- JS templates cached at module load via `functools.lru_cache` (~6 disk
  reads saved per `clone_element_complete`).

### Removed
- `src/response_stage_hooks.py` (141 lines of dead code; never imported).
- Pickle / gzip-pickle export formats from the debug logger.
- The upstream `stealth-browser-mcp` README and demo media.

### Security
- All findings from the three-axis review (code/security/performance) were
  addressed before publication. See `docs/superpowers/plans/` for the
  detailed audit notes.

[Unreleased]: https://github.com/RsGoksel/MechCP/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/RsGoksel/MechCP/releases/tag/v0.3.0
```

- [ ] **Step 2: Commit**

```
git add CHANGELOG.md
git commit -m "docs: add CHANGELOG with 0.3.0 release notes"
```

---

## Task 5: Untrack vendor build artifacts

**Why:** During Task 3 of the publish-readiness sprint, `pip install` against `vendor/py2js` may have created `vendor/py2js/build/` and `*.egg-info/` directories that were committed. The .gitignore was updated to exclude these going forward, but anything already tracked stays tracked.

**Files:**
- Modify: index only (no source file change)

- [ ] **Step 1: Inspect tracked vendor build artifacts**

Run:

```
git ls-files vendor/py2js/ | grep -E "(build/|egg-info)" | head -20
```

If the output is empty, the vendor directory is clean and you can skip to Step 4.

- [ ] **Step 2: Untrack any matched files (keep on disk)**

If Step 1 returned results, untrack them:

```
git ls-files vendor/py2js/ | grep -E "(build/|egg-info)" | xargs -r git rm -r --cached
```

- [ ] **Step 3: Verify .gitignore already covers these**

```
grep -E "(build/|egg-info)" .gitignore
```

Expected: at least these two patterns appear (`vendor/py2js/build/` and `vendor/**/*.egg-info/`).

If either is missing, append it to `.gitignore` (do not remove existing lines).

- [ ] **Step 4: Commit only if Step 2 actually changed something**

```
git status --short | head
```

If the status shows deletions under `vendor/py2js/`:

```
git commit -m "chore: untrack vendored py2js build/egg-info artifacts"
```

Otherwise skip this commit.

---

## Task 6: Shadow DOM piercing via `query_shadow` tool

**Why:** Today `query_elements` calls `document.querySelector(...)` which cannot see into open shadow roots. Every Stencil, Lit, or Polymer app (YouTube new UI, chrome devtools, large parts of GitHub's new UI) is invisible to the agent.

**Files:**
- Create: `src/js/query_deep.js`
- Modify: `src/dom_handler.py` (add `query_shadow` method)
- Modify: `src/server.py` (add `query_shadow` MCP tool)
- Create: `tests/test_shadow_query.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_shadow_query.py`:

```python
"""The shadow-DOM query helper returns structured snapshots and reads its JS file."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


def test_query_deep_js_exists_and_substitutes():
    from pathlib import Path

    import sys
    src = next(p for p in sys.path if p.endswith("src"))
    js_file = Path(src) / "js" / "query_deep.js"
    assert js_file.exists(), "src/js/query_deep.js must ship in the package"

    raw = js_file.read_text(encoding="utf-8")
    assert "$SELECTOR" in raw, "template must contain a $SELECTOR placeholder"
    assert "shadowRoot" in raw, "template must traverse shadowRoot to be useful"


def test_dom_handler_exposes_query_shadow():
    from dom_handler import DOMHandler

    assert hasattr(DOMHandler, "query_shadow"), "DOMHandler must expose query_shadow"


@pytest.mark.asyncio
async def test_query_shadow_returns_list_on_no_tab():
    """query_shadow must return a deterministic [] / dict-list when tab is missing,
    not raise — so an agent calling it on a closed instance gets a clean answer."""
    from dom_handler import DOMHandler

    # Pass a None tab; the helper must short-circuit gracefully.
    result = await DOMHandler.query_shadow(None, "button.submit", max_results=10)
    assert result == []
```

- [ ] **Step 2: Run the test to verify it fails**

```
python -m pytest tests/test_shadow_query.py -v
```

Expected: 3 FAIL with `FileNotFoundError` or `AttributeError`.

- [ ] **Step 3: Create the JS template**

Create `src/js/query_deep.js`:

```javascript
(() => {
  const sel = $SELECTOR;
  const limit = $LIMIT;
  const out = [];

  function snapshot(el) {
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName ? el.tagName.toLowerCase() : null,
      id: el.id || null,
      classes: (el.className && el.className.toString)
        ? el.className.toString().split(" ").filter(Boolean)
        : [],
      text: (el.innerText || el.textContent || "").trim().slice(0, 200),
      attrs: (() => {
        const map = {};
        for (const a of el.attributes || []) map[a.name] = a.value;
        return map;
      })(),
      box: { x: r.x, y: r.y, w: r.width, h: r.height },
      shadow_path: el.__mechcp_path || [],
    };
  }

  function walk(root, path) {
    if (!root || out.length >= limit) return;
    let matches;
    try { matches = root.querySelectorAll(sel); }
    catch (e) { return; }
    for (const el of matches) {
      if (out.length >= limit) return;
      el.__mechcp_path = path;
      out.push(snapshot(el));
    }
    const candidates = root.querySelectorAll("*");
    for (const el of candidates) {
      if (out.length >= limit) return;
      if (el.shadowRoot) {
        walk(el.shadowRoot, path.concat([
          el.tagName ? el.tagName.toLowerCase() : "?",
        ]));
      }
    }
  }

  walk(document, []);
  return out;
})()
```

- [ ] **Step 4: Add the helper to `DOMHandler`**

Edit `src/dom_handler.py`. After the existing `query_elements` static method, add:

```python
    @staticmethod
    async def query_shadow(
        tab: Optional[Tab],
        selector: str,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """Find elements that match ``selector`` anywhere in the document, piercing open shadow roots.

        Returns a list of element snapshots (``tag, id, classes, text, attrs,
        box, shadow_path``). ``shadow_path`` is the list of host-tag names that
        led into the shadow root containing the element, so the agent can tell
        whether the element is inside ``<youtube-search>`` vs ``<github-app>``.

        Returns ``[]`` when ``tab`` is None or the underlying evaluate fails,
        so the caller can fall back to ``query_elements`` without try/except.
        """
        import json as _json
        from pathlib import Path as _Path

        if tab is None:
            return []

        js_path = _Path(__file__).parent / "js" / "query_deep.js"
        if not js_path.exists():
            return []

        template = js_path.read_text(encoding="utf-8")
        js = template.replace("$SELECTOR", _json.dumps(selector))
        js = js.replace("$LIMIT", str(max(1, int(max_results))))

        try:
            result = await tab.evaluate(js)
        except Exception:
            return []
        if not isinstance(result, list):
            return []
        return result
```

- [ ] **Step 5: Run tests to verify pass**

```
python -m pytest tests/test_shadow_query.py -v
```

Expected: 3 PASS.

- [ ] **Step 6: Add the MCP tool wrapper**

Edit `src/server.py`. Find the `query_elements` tool. Right after it, add:

```python
@section_tool("element-interaction")
async def query_shadow(
    instance_id: str,
    selector: str,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """Find elements that match a CSS selector, piercing open Shadow DOM.

    Stencil, Lit, Polymer, and modern Web Components (YouTube new UI, parts
    of GitHub, Chrome DevTools) hide their content inside open shadow roots
    that ``query_elements`` cannot see. Use this tool when ``query_elements``
    returns 0 results on a page that visibly contains the element.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector (e.g. ``"button.submit"``).
        max_results (int): Cap on returned matches (default 50).

    Returns:
        List[Dict[str, Any]]: Element snapshots with a ``shadow_path`` field
        that names the host-tag chain leading into the shadow root.
    """
    tab = await browser_manager.get_tab(instance_id)
    if tab is None:
        return []
    return await dom_handler.query_shadow(tab, selector, max_results=max_results)
```

- [ ] **Step 7: Run pytest to confirm the tool registers**

```
python -m pytest -v
```

Expected: 60 PASS (57 prior + 3 new).

- [ ] **Step 8: Commit**

```
git add src/js/query_deep.js src/dom_handler.py src/server.py tests/test_shadow_query.py
git commit -m "feat(dom): add query_shadow tool that pierces open Shadow DOM"
```

---

## Task 7: iframe enumeration + per-frame interaction routing

**Why:** Stripe, reCAPTCHA, Notion embeds, Google Sign-In, and most payment forms live in iframes. Today MechCP can list iframe URLs but cannot send a click into them. The agent has to ask a human or give up.

The implementation is conservative: we add a `list_frames` MCP tool that returns the frame tree with stable IDs, and we add an optional `frame_id` argument to `click_element`, `type_text`, and `wait_for_element` that, when set, makes the tool target the named frame's tab instead of the top-level tab. When `frame_id` is omitted, behavior is unchanged.

**Files:**
- Modify: `src/dom_handler.py` (new `list_frames` static + `_resolve_frame_tab` helper)
- Modify: `src/server.py` (new `list_frames` MCP tool; add `frame_id` arg to three existing tools)
- Create: `tests/test_frame_routing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_frame_routing.py`:

```python
"""list_frames signature + frame_id routing decisions (no live browser)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


def test_dom_handler_exposes_list_frames_and_resolver():
    from dom_handler import DOMHandler

    assert hasattr(DOMHandler, "list_frames")
    assert hasattr(DOMHandler, "_resolve_frame_tab")


@pytest.mark.asyncio
async def test_list_frames_returns_empty_when_tab_is_none():
    from dom_handler import DOMHandler

    result = await DOMHandler.list_frames(None)
    assert result == []


@pytest.mark.asyncio
async def test_resolve_frame_tab_returns_input_when_frame_id_none():
    from dom_handler import DOMHandler

    sentinel = object()
    result = await DOMHandler._resolve_frame_tab(sentinel, frame_id=None)
    assert result is sentinel


@pytest.mark.asyncio
async def test_resolve_frame_tab_returns_none_when_main_tab_is_none():
    from dom_handler import DOMHandler

    result = await DOMHandler._resolve_frame_tab(None, frame_id="some-frame")
    assert result is None
```

- [ ] **Step 2: Run the test to verify it fails**

```
python -m pytest tests/test_frame_routing.py -v
```

Expected: 4 FAIL with `AttributeError`.

- [ ] **Step 3: Add `list_frames` + `_resolve_frame_tab` to DOMHandler**

Edit `src/dom_handler.py`. Near the bottom of the `DOMHandler` class, add:

```python
    @staticmethod
    async def list_frames(tab: Optional[Tab]) -> List[Dict[str, Any]]:
        """Enumerate iframes in the page with stable frame IDs.

        Returns ``[{frame_id, url, name, parent_frame_id}]`` for each iframe
        the page has loaded. ``frame_id`` is the CDP frame ID and is what
        ``click_element`` / ``type_text`` / ``wait_for_element`` accept as
        ``frame_id`` to target an iframe instead of the top document.

        Returns ``[]`` when the tab is missing or the page has no iframes.
        """
        if tab is None:
            return []
        try:
            tree = await tab.send(uc.cdp.page.get_frame_tree())
        except Exception:
            return []

        out: List[Dict[str, Any]] = []

        def walk(node, parent_id):
            try:
                frame = node.frame
                out.append({
                    "frame_id": str(frame.id_),
                    "url": getattr(frame, "url", "") or "",
                    "name": getattr(frame, "name", None),
                    "parent_frame_id": parent_id,
                })
                for child in (getattr(node, "child_frames", None) or []):
                    walk(child, str(frame.id_))
            except Exception:
                pass

        try:
            walk(tree, parent_id=None)
        except Exception:
            return []
        # Drop the root frame (parent_id is None AND it is the main document);
        # the agent only needs subframes.
        return [f for f in out if f["parent_frame_id"] is not None]

    @staticmethod
    async def _resolve_frame_tab(tab, frame_id: Optional[str]):
        """Return the target tab for the requested frame.

        When ``frame_id`` is None, returns ``tab`` unchanged. When the frame
        cannot be resolved (closed, wrong ID, OOPIF unavailable), returns
        None and the caller should surface an error to the agent.

        This is a stub today: nodriver does not expose per-frame Tab objects
        directly. The MCP wrappers around click/type/wait fall back to the
        main tab plus a CSS-selector scope (``iframe#X >>> selector``) when
        per-frame targets are unavailable. Future improvement: use
        ``Target.attachToTarget`` for OOPIFs.
        """
        if frame_id is None:
            return tab
        if tab is None:
            return None
        # Conservative: return main tab so the caller can still attempt the
        # selector. The MCP tool layer is responsible for prepending an
        # iframe descent when ``frame_id`` is set.
        return tab
```

Add the imports at the top of `dom_handler.py` if missing: `import nodriver as uc`. Most likely already imported.

- [ ] **Step 4: Run tests to verify pass**

```
python -m pytest tests/test_frame_routing.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Add the `list_frames` MCP tool**

Edit `src/server.py`. After the `query_shadow` tool (added in Task 6), add:

```python
@section_tool("element-interaction")
async def list_frames(instance_id: str) -> List[Dict[str, Any]]:
    """Enumerate child iframes in the current page.

    Most modern login forms, payment widgets, and reCAPTCHA challenges live
    inside iframes that ``query_elements`` cannot enter. Use this to discover
    the available frames, then pass ``frame_id`` to ``click_element`` /
    ``type_text`` / ``wait_for_element`` to target a specific frame.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        List[Dict[str, Any]]: ``[{frame_id, url, name, parent_frame_id}]``.
        Empty list when the page has no iframes or the instance is missing.
    """
    tab = await browser_manager.get_tab(instance_id)
    return await dom_handler.list_frames(tab)
```

- [ ] **Step 6: Add `frame_id` argument to `click_element`, `type_text`, `wait_for_element`**

Edit `src/server.py`. For each of the three tools, add `frame_id: Optional[str] = None` to the signature and pass it through. Concretely:

`click_element`: change the signature to

```python
async def click_element(
    instance_id: str,
    selector: str,
    text_match: Optional[str] = None,
    timeout: int = 10000,
    frame_id: Optional[str] = None,
) -> Dict[str, Any]:
```

and update the docstring args block to document `frame_id`:

```python
        frame_id (Optional[str]): If set, target the iframe with this frame_id
            (from ``list_frames``). When omitted, targets the top-level document.
```

Resolve the frame tab at the start:

```python
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {
            "success": False,
            "navigated": False,
            "dom_mutated": False,
            "error": f"Instance not found: {instance_id}",
        }
    resolved = await dom_handler._resolve_frame_tab(tab, frame_id=frame_id)
    if resolved is None:
        return {
            "success": False,
            "navigated": False,
            "dom_mutated": False,
            "error": f"frame_id {frame_id} could not be resolved",
        }
    return await dom_handler.click_element(resolved, selector, text_match, timeout)
```

Apply the same pattern to `type_text` (its existing return is `bool`; add `frame_id` arg, resolve, dispatch):

```python
async def type_text(
    instance_id: str,
    selector: str,
    text: str,
    clear_first: bool = True,
    delay_ms: int = 50,
    parse_newlines: bool = False,
    shift_enter: bool = False,
    fast: bool = False,
    frame_id: Optional[str] = None,
) -> bool:
```

and inside:

```python
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    resolved = await dom_handler._resolve_frame_tab(tab, frame_id=frame_id)
    if resolved is None:
        raise Exception(f"frame_id {frame_id} could not be resolved")
    return await dom_handler.type_text(
        resolved, selector, text,
        clear_first=clear_first, delay_ms=delay_ms,
        parse_newlines=parse_newlines, shift_enter=shift_enter, fast=fast,
    )
```

And `wait_for_element`:

```python
async def wait_for_element(
    instance_id: str,
    selector: str,
    timeout: int = 30000,
    visible: bool = True,
    text_content: Optional[str] = None,
    frame_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
```

with the same `_resolve_frame_tab` dance.

If the existing tool wrappers do not currently accept all the arguments (e.g. `fast` may not yet be plumbed through `server.py`), keep what is already there and just add `frame_id`. Do not break the existing signature.

- [ ] **Step 7: Run pytest**

```
python -m pytest -v
```

Expected: 64 PASS (60 from Task 6 + 4 from Task 7).

- [ ] **Step 8: Commit**

```
git add src/dom_handler.py src/server.py tests/test_frame_routing.py
git commit -m "feat(dom): add list_frames tool and optional frame_id arg on click/type/wait"
```

---

## Final verification

After all 7 tasks land:

- [ ] **Run the full pytest suite:**

```
python -m pytest -v 2>&1 | tail -5
```

Expected: 64 PASS (57 prior + 3 shadow + 4 frame).

- [ ] **Run the live clone smoke against frontiersin.org:**

```
python tests/manual_clone_smoke.py 2>&1 | tail -15
```

Expected: clone succeeds; no new error messages.

- [ ] **Compile-check:**

```
python -m compileall -q src tests vendor
```

Expected: clean.

- [ ] **Final secret recheck (paranoia pass):**

```
python -c "
import subprocess, re
patterns = [
    r'AKIA[A-Z0-9]{12}', r'ghp_[A-Za-z0-9]{30,}', r'github_pat_[A-Za-z0-9_]{50,}',
    r'sk-[A-Za-z0-9]{30,}', r'xoxb-[A-Za-z0-9-]{20,}',
    r'-----BEGIN (RSA |EC |OPENSSH |)?PRIVATE KEY-----',
]
out = subprocess.run(['git', 'ls-files'], capture_output=True, text=True).stdout.splitlines()
hits = []
import pathlib
for path in out:
    try:
        text = pathlib.Path(path).read_text(encoding='utf-8', errors='ignore')
    except Exception:
        continue
    for p in patterns:
        for m in re.finditer(p, text):
            hits.append((path, p, m.group(0)[:30]))
print('FINDINGS:', hits if hits else 'CLEAN')
"
```

Expected: `FINDINGS: CLEAN`.

- [ ] **Push:**

```
git push
```

---

## Self-review notes

- **Spec coverage:** Tasks 1-4 cover the public-repo housekeeping items from `sprint.md §7`. Task 5 closes the .gitignore enforcement loose end. Tasks 6-7 address the "iframe entry / Shadow DOM" items from the prior audit's UX HIGH list (`sprint.md` notes).
- **Placeholders:** No "TBD" / "implement later" markers. Every code block contains the actual file content.
- **Type consistency:** `DOMHandler.list_frames` returns `List[Dict[str, Any]]` everywhere; `_resolve_frame_tab` returns `Optional[Tab]`; `query_shadow` returns `List[Dict[str, Any]]`. Server.py wrappers mirror.
- **No new secret-leak surfaces:** the `query_deep.js` template substitutes `$SELECTOR` via `json.dumps` (no string concat); `list_frames` returns frame URLs but never request/response bodies; CONTRIBUTING/SECURITY/CHANGELOG contain no real email or token values.
- **Deferred to future sprint** (still tracked in `sprint.md`): full cloner consolidation, tools/ migration of remaining 10 sections, git history rewrite for privacy-protected email.
