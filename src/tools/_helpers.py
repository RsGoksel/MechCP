"""Shared singletons and the section-aware tool decorator factory.

Per-domain modules under ``tools/`` import ``section_tool`` from here and
decorate their MCP tool functions. ``register_all`` is the entry point used
by ``server.py`` -- it iterates each domain submodule and triggers tool
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
    s.strip()
    for s in os.environ.get("MECHCP_DISABLED_SECTIONS", "").split(",")
    if s.strip()
}


def is_section_enabled(section: str) -> bool:
    return section not in _DISABLED


def disable_sections(sections: Iterable[str]) -> None:
    _DISABLED.update(sections)


def section_tool(mcp: FastMCP, section: str) -> Callable:
    """Decorator factory -- registers a tool only if its section is enabled."""

    def decorator(func: Callable) -> Callable:
        if is_section_enabled(section):
            return mcp.tool(func)
        return func

    return decorator
