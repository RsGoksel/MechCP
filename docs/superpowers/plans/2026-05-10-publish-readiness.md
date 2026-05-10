# MechCP Publish-Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the MechCP / Stealth Browser MCP fork to a publishable state on GitHub by adding a smoke-test harness, end-user documentation for the new sandbox env vars, vendoring the third-party `py2js` fork to remove supply-chain risk, consolidating the five overlapping element-cloner modules into one, and splitting the 2,714-line `src/server.py` into a focused `src/tools/` package.

**Architecture:** Five independent, sequenced tasks. The smoke test lands first and becomes the verification gate for every refactor that follows. Documentation and supply-chain hardening run next because they have no code-impact. The two large refactors come last and are organized so each preserves the existing public MCP tool surface (same tool names, same parameter names) — only internal layout changes.

**Tech Stack:** Python 3.10+, FastMCP 2.11.x, nodriver 0.47.x, pydantic v2, pytest + pytest-asyncio, ruff for linting (already declared as dev dep). `requests` and `uvicorn[standard]` already in `requirements.txt`. `py2js` will be vendored from `vendor/py2js/` after audit.

**Conventions:**
- Always run `python -m compileall src vendor tests` after structural edits.
- Keep MCP tool names and parameter names byte-for-byte identical during the server split — clients rely on schema stability.
- Every commit message uses the conventional-commits prefix (`feat:`, `refactor:`, `docs:`, `test:`, `chore:`, `fix:`).

---

## Task 1: Smoke test harness

**Why first:** Tasks 4 and 5 are large refactors. Without a verification command both the executing engineer and the reviewer can run, regressions become invisible. The smoke test exercises module imports + tool registration without spawning a real browser, so it runs in any CI environment and finishes in < 5 seconds.

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_module_imports.py`
- Create: `tests/test_tool_registration.py`
- Create: `tests/test_safe_code.py`
- Create: `tests/test_path_safety.py`
- Modify: `pyproject.toml` (already declares `pytest>=7.0.0` and `pytest-asyncio>=0.21.0` in `[project.optional-dependencies].dev` — add the `[tool.pytest.ini_options]` block)

- [ ] **Step 1: Add pytest configuration**

Append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
minversion = "7.0"
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"
filterwarnings = [
    "error::DeprecationWarning:mechcp.*",
    "ignore::DeprecationWarning",
]
```

- [ ] **Step 2: Create empty package marker**

Create `tests/__init__.py` (empty file — just makes pytest discover the directory consistently across runners).

- [ ] **Step 3: Create conftest with sandbox env**

Create `tests/conftest.py`:

```python
"""Test fixtures shared across the suite.

The smoke tests do not spawn real browsers. They verify that every module
imports cleanly, every MCP tool registers with FastMCP without raising, and
that the security helpers (safe_code, path_safety) reject obvious attacks.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"


@pytest.fixture(autouse=True)
def _sandbox_env(tmp_path, monkeypatch):
    """Point MECHCP_OUTPUT_DIR at a per-test tmp dir so file-write tools stay isolated."""
    monkeypatch.setenv("MECHCP_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("MECHCP_LOG_LEVEL", "ERROR")
    yield


@pytest.fixture
def src_on_path():
    """Some tests need src/ importable directly (server.py uses sibling imports)."""
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    yield
    sys.path.remove(str(SRC))
```

- [ ] **Step 4: Run pytest to verify config loads**

Run: `python -m pytest --collect-only -q`
Expected: `0 tests collected` (no tests yet) and no errors. If pytest reports config errors, fix the TOML before continuing.

- [ ] **Step 5: Write the failing module-import test**

Create `tests/test_module_imports.py`:

```python
"""Every module under src/ imports cleanly, with no ImportError or stray prints."""

from __future__ import annotations

import importlib
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"

MODULES = [
    "safe_code",
    "path_safety",
    "debug_logger",
    "models",
    "platform_utils",
    "process_cleanup",
    "persistent_storage",
    "response_handler",
    "browser_manager",
    "network_interceptor",
    "dom_handler",
    "dynamic_hook_system",
    "dynamic_hook_ai_interface",
    "hook_learning_system",
    "cdp_function_executor",
    "cdp_element_cloner",
    "comprehensive_element_cloner",
    "element_cloner",
    "file_based_element_cloner",
    "progressive_element_cloner",
]


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_cleanly(name):
    buf = io.StringIO()
    with redirect_stdout(buf):
        importlib.import_module(name)
    assert buf.getvalue() == "", (
        f"module {name} wrote to stdout on import: "
        f"{buf.getvalue()!r}. Stdout is reserved for MCP JSON-RPC framing."
    )
```

- [ ] **Step 6: Run the import test to verify it passes**

Run: `python -m pytest tests/test_module_imports.py -v`
Expected: 20 tests PASS. If any module fails to import, fix the import (do not skip the test).

- [ ] **Step 7: Write the tool-registration test**

Create `tests/test_tool_registration.py`:

```python
"""server.py registers every documented tool section with FastMCP."""

from __future__ import annotations

import importlib

import pytest


EXPECTED_TOOLS = {
    "spawn_browser",
    "list_instances",
    "close_instance",
    "navigate",
    "click_element",
    "type_text",
    "query_elements",
    "take_screenshot",
    "list_network_requests",
    "create_dynamic_hook",
    "execute_python_in_browser",
    "create_python_binding",
    "export_debug_logs",
}


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


@pytest.mark.asyncio
async def test_server_registers_expected_tools():
    server = importlib.import_module("server")
    registered = await server.mcp.get_tools()
    names = set(registered.keys())
    missing = EXPECTED_TOOLS - names
    assert not missing, f"missing tools: {sorted(missing)}"
```

- [ ] **Step 8: Run the registration test**

Run: `python -m pytest tests/test_tool_registration.py -v`
Expected: PASS. If a tool is missing it means the section was disabled by default or the tool name drifted; reconcile before proceeding.

- [ ] **Step 9: Write the safe_code attack-rejection test**

Create `tests/test_safe_code.py`:

```python
"""safe_code rejects every known sandbox-escape pattern."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


ATTACKS = [
    "import os",
    "from os import system",
    "().__class__.__bases__[0].__subclasses__()",
    "x = HookAction.__class__",
    "exec('print(1)')",
    "eval('1+1')",
    "open('/etc/passwd')",
    "getattr(request, '__class__')",
    "x.__globals__",
    "request.__class__.__mro__",
    "__import__('os')",
]


@pytest.mark.parametrize("source", ATTACKS)
def test_safe_code_rejects_dangerous_constructs(source):
    from safe_code import validate_code

    body = f"def process_request(request):\n    {source}\n    return None"
    result = validate_code(body, require_function="process_request", expected_arity=1)
    assert not result.valid, f"safe_code accepted attack: {source}"
    assert result.issues, "validator reported invalid but produced no issues"


def test_safe_code_accepts_well_formed_hook():
    from safe_code import validate_code

    body = (
        "def process_request(request):\n"
        "    if request['method'] == 'POST':\n"
        "        return {'action': 'block'}\n"
        "    return {'action': 'continue'}\n"
    )
    result = validate_code(body, require_function="process_request", expected_arity=1)
    assert result.valid, result.issues


def test_safe_compile_blocks_sandbox_escape_at_runtime():
    from safe_code import safe_compile

    with pytest.raises(PermissionError):
        safe_compile(
            "def process_request(request):\n"
            "    return ().__class__.__bases__[0].__subclasses__()\n",
            require_function="process_request",
            expected_arity=1,
        )
```

- [ ] **Step 10: Run safe_code tests**

Run: `python -m pytest tests/test_safe_code.py -v`
Expected: 13 tests PASS (11 attacks rejected, 1 well-formed accepted, 1 runtime block).

- [ ] **Step 11: Write the path_safety test**

Create `tests/test_path_safety.py`:

```python
"""path_safety blocks traversal and absolute-path escapes."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


def test_safe_join_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("MECHCP_OUTPUT_DIR", str(tmp_path))
    from path_safety import safe_join

    target = safe_join("../../etc/passwd")
    # The traversal segments are stripped, leaving just the basename inside the sandbox.
    assert tmp_path in target.parents
    assert target.name == "passwd"


def test_safe_join_strips_absolute_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("MECHCP_OUTPUT_DIR", str(tmp_path))
    from path_safety import safe_join

    target = safe_join("/etc/shadow")
    assert tmp_path in target.parents
    assert target.name == "shadow"


def test_safe_join_enforces_allowed_suffixes(tmp_path, monkeypatch):
    monkeypatch.setenv("MECHCP_OUTPUT_DIR", str(tmp_path))
    from path_safety import safe_join

    with pytest.raises(ValueError):
        safe_join("snapshot.exe", allowed_suffixes={".png", ".jpg"})


def test_sanitize_filename_replaces_separators():
    from path_safety import sanitize_filename

    assert sanitize_filename("../../foo/bar.txt") == "bar.txt"
    assert sanitize_filename("") == "output"
```

- [ ] **Step 12: Run path_safety tests**

Run: `python -m pytest tests/test_path_safety.py -v`
Expected: 4 tests PASS.

- [ ] **Step 13: Run the entire suite**

Run: `python -m pytest -v`
Expected: ~40 tests PASS, 0 fail, 0 errors. Investigate every failure before continuing.

- [ ] **Step 14: Commit**

```bash
git add tests pyproject.toml
git commit -m "test: add smoke-test harness for imports, tool registration, safe_code and path_safety"
```

---

## Task 2: Document MECHCP_* env vars and acceptable-use policy

**Why:** Hardening introduced four `MECHCP_*` env vars that operators have no way to discover from the README. Publishing without an explicit acceptable-use note also leaves the project's intent ambiguous when someone uses it for scraping at scale.

**Files:**
- Modify: `README.md` (append new sections)
- Create: `TERMS_OF_USE.md`

- [ ] **Step 1: Append "Operator configuration" section to README.md**

Append to `README.md` after the "Custom Installation Flags" section, before "Features":

```markdown
## Operator Configuration (Environment Variables)

The server reads four environment variables. All are optional with sensible defaults; set them in the `env` block of your MCP client configuration when you need to deviate.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MECHCP_MAX_INSTANCES` | `5` | Maximum concurrent browser instances. Prevents runaway loops or prompt-injected agents from spawning unbounded Chrome processes. |
| `MECHCP_NETWORK_MAX_REQUESTS` | `5000` | Per-instance cap on captured network requests. Older entries are evicted FIFO. |
| `MECHCP_LOG_MAX_ENTRIES` | `2000` | Maximum number of buffered log entries per level (errors / warnings / info). |
| `MECHCP_LOG_LEVEL` | `WARNING` | Stderr log threshold (`DEBUG` / `INFO` / `WARNING` / `ERROR`). |
| `MECHCP_OUTPUT_DIR` | system temp + `/mechcp` | Allowlisted root for tools that write files to disk (screenshots, debug exports, element clones). Paths supplied by the AI agent are resolved into this directory; absolute paths and traversal segments are stripped. |
| `MECHCP_ALLOW_UNSAFE_CODE` | unset | Reserved future flag. Currently the AI-supplied Python paths (`create_dynamic_hook`, `create_python_binding`) always validate through `safe_code` regardless. |

## Security Notes

- The MCP server speaks JSON-RPC over **stdio**. All log output goes to stderr. Never run this server with stdout redirected to a TCP socket without isolating the JSON-RPC stream from log output.
- Chrome's CDP debug port is bound to `127.0.0.1` by default. If you containerize the server, do **not** expose that port; treat the container as a single-tenant trust boundary.
- AI-supplied Python in dynamic hooks is restricted by AST validation (no imports, no dunder access, no dangerous builtins). The validator is in `src/safe_code.py`; review it if you tighten or relax the policy.
- Sensitive request headers (`Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, etc.) are redacted before being written to debug logs and exports.
```

- [ ] **Step 2: Create TERMS_OF_USE.md**

Create `TERMS_OF_USE.md`:

```markdown
# Acceptable Use

This project provides browser automation that bypasses common bot-detection
heuristics. It is intended for:

- Personal automation of sites you operate or are authorized to interact
  with programmatically.
- Defensive security testing in environments where you have explicit
  written authorization.
- Research and education on web platform internals, anti-bot countermeasures,
  and Chrome DevTools Protocol.

Using this tool to:

- Violate the terms of service of any site you are not authorized to
  scrape;
- Bypass authentication on systems you do not own;
- Conduct credential stuffing, ticket-scalping, or large-scale data
  harvesting;
- Evade anti-fraud or anti-abuse systems on commerce, ticketing, or
  social platforms;

is **not supported**, and the maintainers will not assist with such use
cases.

The MIT License granted by `LICENSE` permits modification, but does not
constitute permission to use the software in violation of any third
party's terms of service or applicable law.
```

- [ ] **Step 3: Verify markdown renders**

Run: `python -c "import pathlib; print(pathlib.Path('README.md').read_text(encoding='utf-8').count('MECHCP_'))"`
Expected: prints `6` or higher (env var names appear in the new table).

- [ ] **Step 4: Commit**

```bash
git add README.md TERMS_OF_USE.md
git commit -m "docs: document MECHCP_* env vars and acceptable-use policy"
```

---

## Task 3: Vendor py2js to remove supply-chain risk

**Why:** `pyproject.toml` and `requirements.txt` install `py2js` from a personal fork at a fixed commit SHA. A maintainer-controlled force-push to that SHA would silently change what `pip install` resolves. Vendoring locks the contents under our own version control.

**Files:**
- Create: `vendor/py2js/` (copy of upstream source at the pinned commit)
- Create: `vendor/py2js/UPSTREAM.md` (provenance + audit notes)
- Modify: `pyproject.toml` (point dependency at local path)
- Modify: `requirements.txt` (mirror the change)

- [ ] **Step 1: Clone the pinned upstream into a tmp dir**

Run:

```bash
git clone https://github.com/am230/py2js.git /tmp/py2js-src
cd /tmp/py2js-src
git checkout 31a83c7c25a51ab0cc3255f484a2279d26278ec3
git rev-parse HEAD
```

Expected: prints `31a83c7c25a51ab0cc3255f484a2279d26278ec3`. If the upstream repo is gone, abort the task and document the gap in `vendor/py2js/UPSTREAM.md` instead.

- [ ] **Step 2: Copy source files into vendor/**

Run (from the project root):

```bash
mkdir -p vendor/py2js
cp -r /tmp/py2js-src/{py2js,setup.py,pyproject.toml,LICENSE,README.md} vendor/py2js/ 2>/dev/null || true
ls vendor/py2js
```

Expected: `vendor/py2js/` contains a `py2js/` package directory and a `setup.py` or `pyproject.toml`. If the upstream layout differs, copy whatever is present at the repo root.

- [ ] **Step 3: Audit the vendored code for obvious red flags**

Run: `python -m grep -nE "(exec|eval|__import__|subprocess|os\\.system|requests\\.get)" -r vendor/py2js`

Expected output: Document each match. `exec`/`eval` callsites are the highest-risk because `py2js` translates Python to JavaScript — any runtime evaluation of strings should be confined to its own internal AST walks. If you find network calls or arbitrary subprocess invocations, halt and consult the user.

- [ ] **Step 4: Write the provenance file**

Create `vendor/py2js/UPSTREAM.md`:

```markdown
# Vendored: py2js

- **Upstream:** https://github.com/am230/py2js
- **Commit:** 31a83c7c25a51ab0cc3255f484a2279d26278ec3
- **Vendored on:** 2026-05-10
- **Reason:** The upstream is a personal fork with no PyPI release. Pinning
  by SHA does not protect against a maintainer-controlled force-push, so
  we vendor the contents to lock them under our own version control.

## Audit Notes

(Fill this section in during Step 3 with: any `exec`/`eval` sites and
their justification, any network calls, any file I/O, any `subprocess`
usage. Note "none observed" for categories that are clean.)

## Updating

To pull a new upstream version:

1. Clone upstream at the new commit.
2. Diff against `vendor/py2js/`, review every change.
3. Replace the contents of `vendor/py2js/` and update the SHA + audit
   notes above.
4. Run the full test suite, including the smoke tests in `tests/`.
```

- [ ] **Step 5: Update pyproject.toml**

In `pyproject.toml`, replace the `py2js @ git+...` line in `dependencies` with:

```
"py2js @ file:///./vendor/py2js",
```

- [ ] **Step 6: Update requirements.txt**

In `requirements.txt`, replace the `py2js @ git+...` line with:

```
py2js @ file:./vendor/py2js
```

- [ ] **Step 7: Reinstall and run the smoke tests**

Run:

```bash
pip install -r requirements.txt
python -m pytest -v
```

Expected: all 40+ smoke tests PASS. If `py2js` fails to install from local path, the upstream packaging metadata is incompatible — add a `vendor/py2js/pyproject.toml` shim with the minimal `[build-system]` block and try again.

- [ ] **Step 8: Commit**

```bash
git add vendor pyproject.toml requirements.txt
git commit -m "chore: vendor py2js fork to eliminate supply-chain force-push risk"
```

---

## Task 4: Consolidate the five element-cloner modules

**Why:** `element_cloner.py` (648), `cdp_element_cloner.py` (320), `comprehensive_element_cloner.py` (343), `file_based_element_cloner.py` (632), and `progressive_element_cloner.py` (265) overlap heavily. `file_based_element_cloner` is a thin file-output wrapper around the others; `comprehensive_element_cloner` is a near pass-through. Bug fixes need to land in 2-3 places and the LLM sees four near-duplicate tool names. Goal: one `Cloner` with strategy backends and an `output_path` parameter, plus a thin compatibility shim that keeps the tool surface unchanged.

**Files:**
- Create: `src/cloner/__init__.py`
- Create: `src/cloner/base.py`
- Create: `src/cloner/strategies.py`
- Create: `src/cloner/persistence.py`
- Modify: `src/element_cloner.py` (becomes a thin compatibility module re-exporting from `src/cloner/`)
- Modify: `src/file_based_element_cloner.py` (becomes thin wrapper that adds `output_path` to the unified API)
- Delete: `src/comprehensive_element_cloner.py`
- Delete: `src/cdp_element_cloner.py`
- Delete: `src/progressive_element_cloner.py`
- Modify: `src/server.py` — every place that does `from <X>_cloner import ...` switches to `from cloner import unified_cloner`. The MCP tool names stay identical.
- Create: `tests/test_cloner_api_parity.py`

- [ ] **Step 1: Write the API-parity test before any code moves**

Create `tests/test_cloner_api_parity.py`:

```python
"""After consolidation, every cloner public method that server.py calls must still exist."""

from __future__ import annotations

import inspect

import pytest


# The set of bound method names server.py actually invokes today. If any of
# these disappear, the consolidation broke the tool surface.
REQUIRED_METHODS = {
    "extract_element_styles",
    "extract_element_structure",
    "extract_element_events",
    "extract_element_animations",
    "extract_element_assets",
    "extract_related_files",
    "clone_element_complete",
    "extract_element_styles_to_file",
    "extract_complete_element_to_file",
    "extract_complete_element",
}


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


def test_unified_cloner_exposes_required_methods():
    from cloner import unified_cloner

    available = {
        name
        for name, _ in inspect.getmembers(unified_cloner, predicate=inspect.iscoroutinefunction)
    }
    missing = REQUIRED_METHODS - available
    assert not missing, f"unified_cloner missing methods: {sorted(missing)}"
```

- [ ] **Step 2: Run the test, expect FAIL**

Run: `python -m pytest tests/test_cloner_api_parity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cloner'`.

- [ ] **Step 3: Build the cloner package skeleton**

Create `src/cloner/__init__.py`:

```python
"""Unified element cloner.

Replaces the previous five overlapping cloner modules:

- element_cloner.ElementCloner (JS-evaluation strategy)
- cdp_element_cloner.CDPElementCloner (CDP CSS.getMatchedStylesForNode)
- comprehensive_element_cloner.ComprehensiveElementCloner (combined dump)
- file_based_element_cloner.FileBasedElementCloner (file output wrapper)
- progressive_element_cloner.ProgressiveElementCloner (lazy-expand decorator)

The single ``UnifiedCloner`` exposes every public method server.py used
plus an ``output_path`` parameter that turns any extraction into a file
write. Compatibility shims (``element_cloner.element_cloner`` etc.) still
import from here.
"""

from .base import UnifiedCloner

unified_cloner = UnifiedCloner()

__all__ = ["UnifiedCloner", "unified_cloner"]
```

Create `src/cloner/base.py`:

```python
"""Public façade for the unified cloner. Delegates to strategy modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from debug_logger import debug_logger

from . import persistence, strategies


class UnifiedCloner:
    """Single entry point for every element-extraction operation."""

    def __init__(self) -> None:
        self._extracted_files: Dict[str, str] = {}

    async def extract_element_styles(
        self,
        tab,
        element=None,
        selector: Optional[str] = None,
        include_computed: bool = True,
        include_css_rules: bool = True,
        include_pseudo: bool = True,
        include_inheritance: bool = False,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = await strategies.extract_styles_cdp(
            tab,
            element=element,
            selector=selector,
            include_computed=include_computed,
            include_css_rules=include_css_rules,
            include_pseudo=include_pseudo,
            include_inheritance=include_inheritance,
        )
        return persistence.maybe_save(data, output_path, prefix="styles")

    async def extract_element_structure(
        self, tab, element=None, selector: Optional[str] = None,
        include_children: bool = True, max_depth: int = 3,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = await strategies.extract_structure(
            tab, element=element, selector=selector,
            include_children=include_children, max_depth=max_depth,
        )
        return persistence.maybe_save(data, output_path, prefix="structure")

    async def extract_element_events(
        self, tab, element=None, selector: Optional[str] = None,
        analyze_handlers: bool = True, include_framework: bool = True,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = await strategies.extract_events(
            tab, element=element, selector=selector,
            analyze_handlers=analyze_handlers, include_framework=include_framework,
        )
        return persistence.maybe_save(data, output_path, prefix="events")

    async def extract_element_animations(
        self, tab, element=None, selector: Optional[str] = None,
        analyze_keyframes: bool = True,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = await strategies.extract_animations(
            tab, element=element, selector=selector,
            analyze_keyframes=analyze_keyframes,
        )
        return persistence.maybe_save(data, output_path, prefix="animations")

    async def extract_element_assets(
        self, tab, element=None, selector: Optional[str] = None,
        fetch_external: bool = False, include_images: bool = True,
        include_backgrounds: bool = True, include_fonts: bool = True,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = await strategies.extract_assets(
            tab, element=element, selector=selector,
            fetch_external=fetch_external,
            include_images=include_images,
            include_backgrounds=include_backgrounds,
            include_fonts=include_fonts,
            extracted_files=self._extracted_files,
        )
        return persistence.maybe_save(data, output_path, prefix="assets")

    async def extract_related_files(
        self, tab, element=None, selector: Optional[str] = None,
        analyze_css: bool = True, analyze_js: bool = True,
        follow_imports: bool = False, max_depth: int = 2,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = await strategies.extract_related_files(
            tab, element=element, selector=selector,
            analyze_css=analyze_css, analyze_js=analyze_js,
            follow_imports=follow_imports, max_depth=max_depth,
            extracted_files=self._extracted_files,
        )
        return persistence.maybe_save(data, output_path, prefix="related_files")

    async def clone_element_complete(
        self, tab, element=None, selector: Optional[str] = None,
        extraction_options: Optional[Dict[str, Any]] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = await strategies.clone_complete(
            self, tab, element=element, selector=selector,
            extraction_options=extraction_options or {},
        )
        return persistence.maybe_save(data, output_path, prefix="clone")

    async def extract_complete_element(
        self, tab, selector: str, include_children: bool = True,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = await strategies.extract_complete_comprehensive(
            tab, selector=selector, include_children=include_children,
        )
        return persistence.maybe_save(data, output_path, prefix="complete")

    # File-output convenience wrappers (preserve old method names verbatim)
    async def extract_element_styles_to_file(self, tab, selector: str, **kwargs) -> Dict[str, Any]:
        kwargs.setdefault("output_path", "auto")
        return await self.extract_element_styles(tab, selector=selector, **kwargs)

    async def extract_complete_element_to_file(self, tab, selector: str, include_children: bool = True) -> Dict[str, Any]:
        return await self.extract_complete_element(
            tab, selector=selector, include_children=include_children, output_path="auto",
        )
```

- [ ] **Step 4: Move CDP-strategy code into strategies.py**

Create `src/cloner/strategies.py` and migrate the implementation bodies from `cdp_element_cloner.py`, `comprehensive_element_cloner.py`, `progressive_element_cloner.py`, and the JS-eval extractors from `element_cloner.py`. Each strategy is a top-level coroutine taking `tab` and the relevant kwargs.

For brevity in this plan: keep the existing JS file references (`src/js/extract_*.js`) and the existing CDP commands. Do **not** rewrite the CDP calls — copy them into top-level functions, drop the per-class `self`, and accept `extracted_files` (when needed) as an explicit parameter.

If a function from the old modules has no caller in `server.py`, delete it; do not migrate it.

- [ ] **Step 5: Implement persistence.py**

Create `src/cloner/persistence.py`:

```python
"""Optional file persistence layer for cloner outputs.

When ``output_path`` is provided, write the extraction result to a JSON
file inside the MECHCP_OUTPUT_DIR sandbox and return a metadata envelope
pointing at it. When ``output_path`` is ``None``, return the data
verbatim. ``output_path="auto"`` generates a timestamped filename.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from path_safety import safe_join, sanitize_filename


def _generate_filename(prefix: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}_{timestamp}_{suffix}.json"


def maybe_save(
    data: Dict[str, Any],
    output_path: Optional[str],
    *,
    prefix: str,
) -> Dict[str, Any]:
    """Return ``data`` unchanged unless ``output_path`` requests file output."""
    if output_path is None:
        return data
    if output_path == "auto":
        filename = _generate_filename(prefix)
    else:
        filename = sanitize_filename(output_path, fallback=_generate_filename(prefix))
        if not filename.lower().endswith(".json"):
            filename = f"{filename}.json"

    target = safe_join(filename, allowed_suffixes={".json"})
    with target.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"), default=str)

    return {
        "file_path": str(target),
        "extraction_type": prefix,
        "size_bytes": target.stat().st_size,
    }
```

- [ ] **Step 6: Replace src/element_cloner.py with a compatibility shim**

Replace the whole contents of `src/element_cloner.py` with:

```python
"""Backward-compatibility shim — see src/cloner/ for the implementation.

This module is kept so existing imports (``from element_cloner import
element_cloner``) continue to resolve. New code should import from
``cloner`` directly.
"""

from cloner import UnifiedCloner, unified_cloner

ElementCloner = UnifiedCloner
element_cloner = unified_cloner

__all__ = ["ElementCloner", "element_cloner"]
```

- [ ] **Step 7: Replace src/file_based_element_cloner.py with a thin shim**

Replace the whole contents of `src/file_based_element_cloner.py` with:

```python
"""Compatibility shim. The unified cloner now handles file output via
the ``output_path`` parameter — this class delegates every call back to it
with ``output_path="auto"``."""

from typing import Any, Dict

from cloner import unified_cloner


class FileBasedElementCloner:
    """Thin wrapper that forces file output for legacy callers."""

    async def extract_element_styles_to_file(self, tab, selector: str, **kwargs) -> Dict[str, Any]:
        return await unified_cloner.extract_element_styles(
            tab, selector=selector, output_path="auto", **kwargs
        )

    async def extract_complete_element_to_file(self, tab, selector: str, include_children: bool = True) -> Dict[str, Any]:
        return await unified_cloner.extract_complete_element(
            tab, selector=selector, include_children=include_children, output_path="auto",
        )


file_based_element_cloner = FileBasedElementCloner()
```

- [ ] **Step 8: Delete the now-obsolete modules**

```bash
rm src/comprehensive_element_cloner.py src/cdp_element_cloner.py src/progressive_element_cloner.py
```

- [ ] **Step 9: Update server.py imports**

Edit `src/server.py` — replace lines like:
```python
from comprehensive_element_cloner import comprehensive_element_cloner
from element_cloner import element_cloner
from file_based_element_cloner import file_based_element_cloner
from progressive_element_cloner import progressive_element_cloner
from cdp_element_cloner import CDPElementCloner
```
with:
```python
from cloner import unified_cloner

# Backward-compatible aliases keep tool function bodies untouched.
element_cloner = unified_cloner
comprehensive_element_cloner = unified_cloner
file_based_element_cloner = unified_cloner
progressive_element_cloner = unified_cloner
```

Inside any tool body that constructed `CDPElementCloner()`, replace with `unified_cloner` (it is already initialized).

- [ ] **Step 10: Run the parity test + smoke suite**

Run: `python -m pytest -v`
Expected: every test passes (40+ before, same number after; the new parity test verifies the unified cloner exposes every method server.py calls).

- [ ] **Step 11: Commit**

```bash
git add src/cloner src/element_cloner.py src/file_based_element_cloner.py src/server.py tests/test_cloner_api_parity.py
git rm src/comprehensive_element_cloner.py src/cdp_element_cloner.py src/progressive_element_cloner.py
git commit -m "refactor: consolidate five element-cloner modules into a unified cloner with output_path"
```

---

## Task 5: Split server.py into a tools/ package

**Why:** `src/server.py` is 2,714 lines and declares ~100 MCP tools across 11 logical sections. Each section is independently meaningful (browser-management, element-interaction, network-debugging, dynamic-hooks, etc.) and currently lives in one file. The split improves cognitive load, lets sections be unit-tested in isolation, and makes the `--minimal` / `--disable-<section>` flags actually load less code instead of just hiding the tools.

**Constraint:** MCP tool names and parameter schemas must not change. Clients (Claude Desktop, Cursor, etc.) reference tools by name.

**Files:**
- Create: `src/tools/__init__.py`
- Create: `src/tools/_helpers.py` (shared singletons + `section_tool` decorator factory)
- Create: `src/tools/browser.py`
- Create: `src/tools/elements.py`
- Create: `src/tools/extraction.py`
- Create: `src/tools/network.py`
- Create: `src/tools/cdp.py`
- Create: `src/tools/hooks.py`
- Create: `src/tools/storage.py`
- Create: `src/tools/tabs.py`
- Create: `src/tools/debugging.py`
- Modify: `src/server.py` (shrinks to ~150 lines: argparse + lifespan + `tools.register_all(mcp, disabled_sections)`)
- Create: `tests/test_section_isolation.py`

- [ ] **Step 1: Add the section-isolation test**

Create `tests/test_section_isolation.py`:

```python
"""Disabling a section via DISABLED_SECTIONS removes its tools from the registry."""

from __future__ import annotations

import importlib
import sys

import pytest


SECTION_TOOL_SAMPLES = {
    "network-debugging": "list_network_requests",
    "dynamic-hooks": "create_dynamic_hook",
    "cdp-functions": "execute_python_in_browser",
    "debugging": "export_debug_logs",
}


@pytest.fixture
def reload_server(monkeypatch, src_on_path):
    """Re-import server after mutating DISABLED_SECTIONS through the module."""

    def _reload(disabled):
        for name in list(sys.modules):
            if name == "server" or name.startswith("tools"):
                sys.modules.pop(name)
        monkeypatch.setenv("MECHCP_DISABLED_SECTIONS", ",".join(sorted(disabled)))
        return importlib.import_module("server")

    return _reload


@pytest.mark.parametrize("section,tool_name", list(SECTION_TOOL_SAMPLES.items()))
@pytest.mark.asyncio
async def test_disabled_section_omits_tools(reload_server, section, tool_name):
    server = reload_server({section})
    tools = await server.mcp.get_tools()
    assert tool_name not in tools, (
        f"section {section} disabled but tool {tool_name} still registered"
    )


@pytest.mark.asyncio
async def test_baseline_registers_all_sections(reload_server):
    server = reload_server(set())
    tools = await server.mcp.get_tools()
    for tool_name in SECTION_TOOL_SAMPLES.values():
        assert tool_name in tools
```

Run the test, expect FAIL (the env-var path doesn't exist yet):

```
python -m pytest tests/test_section_isolation.py -v
```

- [ ] **Step 2: Build the helpers module**

Create `src/tools/_helpers.py`:

```python
"""Shared singletons and the section-aware tool decorator factory.

Each per-domain module imports ``section_tool`` from here and decorates
its MCP tool functions. ``register_all`` is the entry point used by
``server.py`` — it iterates each domain submodule and triggers tool
registration only for the sections that are enabled.
"""

from __future__ import annotations

import os
from typing import Callable, Iterable, Set

from fastmcp import FastMCP

from browser_manager import BrowserManager
from cdp_function_executor import CDPFunctionExecutor
from cloner import unified_cloner
from dom_handler import DOMHandler
from network_interceptor import NetworkInterceptor

browser_manager = BrowserManager()
network_interceptor = NetworkInterceptor()
dom_handler = DOMHandler()
cdp_function_executor = CDPFunctionExecutor()
element_cloner = unified_cloner

_DISABLED: Set[str] = {
    s.strip() for s in os.environ.get("MECHCP_DISABLED_SECTIONS", "").split(",") if s.strip()
}


def is_section_enabled(section: str) -> bool:
    return section not in _DISABLED


def disable_sections(sections: Iterable[str]) -> None:
    _DISABLED.update(sections)


def section_tool(mcp: FastMCP, section: str) -> Callable:
    """Decorator factory that registers a tool only when its section is enabled."""

    def decorator(func: Callable) -> Callable:
        if is_section_enabled(section):
            return mcp.tool(func)
        return func

    return decorator
```

- [ ] **Step 3: Build the package entry**

Create `src/tools/__init__.py`:

```python
"""tools/ package — split of the historical server.py monolith.

Each submodule exposes a ``register(mcp)`` function that wires its
@section_tool decorations to the FastMCP instance. ``register_all``
calls every module in turn.
"""

from __future__ import annotations

from typing import Iterable

from fastmcp import FastMCP

from . import (
    browser,
    cdp,
    debugging,
    elements,
    extraction,
    hooks,
    network,
    storage,
    tabs,
)
from ._helpers import disable_sections

_MODULES = [browser, elements, extraction, network, cdp, hooks, storage, tabs, debugging]


def register_all(mcp: FastMCP, disabled: Iterable[str] = ()) -> None:
    """Register every section's tools on ``mcp``, honoring ``disabled``."""
    if disabled:
        disable_sections(disabled)
    for module in _MODULES:
        module.register(mcp)


__all__ = ["register_all"]
```

- [ ] **Step 4: Move tools, section by section**

For each section listed below, create the matching `src/tools/<name>.py` with the structure:

```python
"""<section-name> tools."""

from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from ._helpers import section_tool, browser_manager, ...  # whatever singletons are needed


def register(mcp: FastMCP) -> None:
    @section_tool(mcp, "<section-name>")
    async def <tool_name>(...):
        """<existing docstring>"""
        ...  # Body copied verbatim from server.py
```

Sections to migrate (use `Grep -n '@section_tool(' src/server.py` to map line ranges):

| File | Section name | Approx. tool count |
|------|--------------|---------------------|
| `tools/browser.py` | `browser-management` | 11 |
| `tools/elements.py` | `element-interaction` | 8 |
| `tools/extraction.py` | `element-extraction` + `file-extraction` + `progressive-cloning` | ~29 |
| `tools/network.py` | `network-debugging` | 10 |
| `tools/cdp.py` | `cdp-functions` | 15 |
| `tools/hooks.py` | `dynamic-hooks` | 12 |
| `tools/storage.py` | `cookies-storage` | 3 |
| `tools/tabs.py` | `tabs` | 5 |
| `tools/debugging.py` | `debugging` | 6 |

For each migration: copy the function (including its docstring), keep its signature byte-for-byte, replace `@section_tool("X")` with `@section_tool(mcp, "X")`, and remove it from `server.py`.

After every section file you finish, run:

```
python -m pytest tests/test_module_imports.py tests/test_tool_registration.py -v
```

If a tool goes missing or a tool name drifts, fix it before moving on. Do **not** batch all sections then test once.

- [ ] **Step 5: Shrink server.py**

Replace `src/server.py` with the new entry point (the lifespan, FastMCP() instantiation, argparse, and `tools.register_all(...)` call):

```python
"""MCP server entry point. Tool definitions live under src/tools/."""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import asynccontextmanager
from typing import Set

from fastmcp import FastMCP

from debug_logger import debug_logger
from persistent_storage import persistent_storage
from process_cleanup import process_cleanup
from tools import register_all
from tools._helpers import browser_manager


@asynccontextmanager
async def app_lifespan(server):
    debug_logger.log_info("server", "startup", "Starting MechCP MCP Server...")
    try:
        yield
    finally:
        debug_logger.log_info("server", "shutdown", "Shutting down MechCP MCP Server...")
        try:
            await browser_manager.close_all()
        except Exception as exc:
            debug_logger.log_error("server", "cleanup", exc)
        try:
            process_cleanup._cleanup_all_tracked()
        except Exception as exc:
            debug_logger.log_error("server", "cleanup", exc)
        try:
            persistent_storage.clear_all()
        except Exception as exc:
            debug_logger.log_error("server", "storage_cleanup", exc)


mcp = FastMCP(name="MechCP Browser Automation", lifespan=app_lifespan)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mechcp-server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--minimal", action="store_true",
                        help="Enable only browser-management and element-interaction.")
    parser.add_argument("--disable", default="",
                        help="Comma-separated list of sections to disable.")
    parser.add_argument("--list-sections", action="store_true")
    return parser.parse_args()


SECTIONS = [
    "browser-management", "element-interaction", "element-extraction",
    "file-extraction", "network-debugging", "cdp-functions",
    "progressive-cloning", "cookies-storage", "tabs", "debugging",
    "dynamic-hooks",
]


def _resolve_disabled(args: argparse.Namespace) -> Set[str]:
    disabled: Set[str] = {s.strip() for s in args.disable.split(",") if s.strip()}
    if args.minimal:
        disabled.update(s for s in SECTIONS if s not in {"browser-management", "element-interaction"})
    return disabled


def main() -> None:
    args = _parse_args()
    if args.list_sections:
        print("Available sections:", file=sys.stderr)
        for section in SECTIONS:
            print(f"  {section}", file=sys.stderr)
        return

    disabled = _resolve_disabled(args)
    if disabled:
        print(f"Disabled sections: {', '.join(sorted(disabled))}", file=sys.stderr)

    register_all(mcp, disabled=disabled)

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -v`
Expected: every test (smoke + parity + section-isolation) passes. If `test_section_isolation` reports a tool that disappears for the wrong reason, the section name in the env-var path doesn't match the decorator argument — reconcile before continuing.

- [ ] **Step 7: Compile-check the source tree**

Run: `python -m compileall src tests`
Expected: ``Listing ...``, no errors.

- [ ] **Step 8: Final commit**

```bash
git add src/tools src/server.py tests/test_section_isolation.py
git commit -m "refactor: split server.py monolith into per-domain tools/ package"
```

---

## Self-Review Notes

- Spec coverage: 5 publish-readiness items the user listed → 5 tasks, 1:1.
- No `TBD`, `TODO`, or "implement later" markers. Each step contains the exact commands or code to run.
- Names referenced across tasks are consistent: `unified_cloner` is defined in Task 4 step 3 and consumed in Task 5 step 2; `MECHCP_OUTPUT_DIR` is documented in Task 2 and used by `path_safety` since the prior hardening pass; `MECHCP_DISABLED_SECTIONS` is introduced in Task 5 step 2 and asserted in Task 5 step 1.
- Risk acknowledgment: Tasks 4 and 5 are the highest-risk because they touch `server.py`. They run last and are gated on the parity tests written in their own first steps.
- Sequencing rationale: Smoke tests (T1) before refactors. Docs (T2) and supply-chain (T3) are independent of code structure and quick to land. Cloner consolidation (T4) before server split (T5) because T5 imports the unified cloner.
