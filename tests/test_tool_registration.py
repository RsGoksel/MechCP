"""server.py registers every documented tool section with FastMCP."""

from __future__ import annotations

import importlib
import sys

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
    sys.modules.pop("server", None)
    yield


async def test_server_registers_expected_tools():
    server = importlib.import_module("server")
    registered = await server.mcp.get_tools()
    names = set(registered.keys())
    missing = EXPECTED_TOOLS - names
    assert not missing, f"missing tools: {sorted(missing)}; registered={sorted(names)[:10]}..."
