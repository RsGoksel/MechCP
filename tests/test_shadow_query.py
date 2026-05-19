"""The shadow-DOM query helper returns structured snapshots and reads its JS file."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


def test_query_deep_js_exists_and_substitutes():
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
    """query_shadow must return a deterministic [] when tab is missing,
    not raise, so an agent calling it on a closed instance gets a clean answer.
    """
    from dom_handler import DOMHandler

    result = await DOMHandler.query_shadow(None, "button.submit", max_results=10)
    assert result == []
