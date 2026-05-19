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

_MINIMAL_DISABLED = {
    "element-extraction", "file-extraction", "network-debugging",
    "cdp-functions", "progressive-cloning", "cookies-storage",
    "tabs", "debugging", "dynamic-hooks",
}


def _initial_disabled() -> Set[str]:
    """Compute initial disabled set from env vars at module-import time.

    Honors both ``MECHCP_DISABLED_SECTIONS`` (explicit list) and
    ``MECHCP_MINIMAL`` (preset that disables every section except
    browser-management and element-interaction).
    """
    sections: Set[str] = {
        s.strip()
        for s in os.environ.get("MECHCP_DISABLED_SECTIONS", "").split(",")
        if s.strip()
    }
    if os.environ.get("MECHCP_MINIMAL", "").strip().lower() in {"1", "true", "yes"}:
        sections.update(_MINIMAL_DISABLED)
    return sections


_DISABLED: Set[str] = _initial_disabled()


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
