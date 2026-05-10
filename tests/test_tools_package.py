"""tools/ package wiring is correct."""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    sys.modules.pop("server", None)
    sys.modules.pop("tools", None)
    sys.modules.pop("tools._helpers", None)
    sys.modules.pop("tools.tabs", None)
    yield


async def test_tabs_tools_register_through_tools_package():
    server = importlib.import_module("server")
    tools_dict = await server.mcp.get_tools()
    expected = {
        "list_tabs",
        "switch_tab",
        "close_tab",
        "get_active_tab",
        "new_tab",
    }
    missing = expected - set(tools_dict.keys())
    assert not missing, f"missing tools after split: {sorted(missing)}"


def test_tools_register_all_callable():
    tools = importlib.import_module("tools")
    assert callable(tools.register_all)
