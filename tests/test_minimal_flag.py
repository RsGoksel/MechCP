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
    # Drop server AND every cached tools/* module so register_all rebuilds
    # against the fresh FastMCP instance the new server module creates.
    for name in list(sys.modules):
        if name == "server" or name == "tools" or name.startswith("tools."):
            sys.modules.pop(name, None)
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
