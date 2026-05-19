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
async def test_resolve_frame_tab_returns_none_for_unsupported_frame_id():
    """Per-frame routing is intentionally a stub today (nodriver does not
    expose per-frame Tab objects). Resolver must return None so the MCP
    wrapper can surface an explicit 'not yet supported' error instead of
    silently sending the click to the top-level document.
    """
    from dom_handler import DOMHandler

    sentinel = object()
    result = await DOMHandler._resolve_frame_tab(sentinel, frame_id="some-frame")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_frame_tab_returns_none_when_main_tab_is_none():
    from dom_handler import DOMHandler

    result = await DOMHandler._resolve_frame_tab(None, frame_id="some-frame")
    assert result is None
