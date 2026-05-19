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
    # Drop server AND every cached tools/* module so register_all rebuilds
    # against a fresh FastMCP. Other tests reload server with disabled
    # sections; without this pop the leftover _DISABLED state would
    # incorrectly hide tools from THIS test.
    for name in list(sys.modules):
        if name == "server" or name == "tools" or name.startswith("tools."):
            sys.modules.pop(name, None)
    yield


async def test_server_registers_expected_tools():
    server = importlib.import_module("server")
    registered = await server.mcp.get_tools()
    names = set(registered.keys())
    missing = EXPECTED_TOOLS - names
    assert not missing, f"missing tools: {sorted(missing)}; registered={sorted(names)[:10]}..."
