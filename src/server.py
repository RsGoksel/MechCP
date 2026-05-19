"""MechCP MCP server entry point.

All tool definitions live under ``src/tools/``. This module wires up the
FastMCP lifespan, the disable-section env vars and CLI flags, the resource
endpoints that expose browser state via ``browser://`` URIs, and the
argparse main block.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastmcp import FastMCP

from debug_logger import debug_logger
from persistent_storage import persistent_storage
from process_cleanup import process_cleanup


_ALL_SECTIONS = {
    "browser-management", "element-interaction", "element-extraction",
    "file-extraction", "network-debugging", "cdp-functions",
    "progressive-cloning", "cookies-storage", "tabs", "debugging",
    "dynamic-hooks",
}
_MINIMAL_DISABLED = _ALL_SECTIONS - {"browser-management", "element-interaction"}


def _initial_disabled_sections() -> set[str]:
    """Compute initial disabled-section set from env vars at import time.

    Honors ``MECHCP_DISABLED_SECTIONS`` (comma-separated list) and a boolean
    ``MECHCP_MINIMAL`` flag. Argparse later in ``__main__`` can still extend
    the set.
    """
    sections: set[str] = set()
    raw = os.environ.get("MECHCP_DISABLED_SECTIONS", "")
    for name in raw.split(","):
        name = name.strip()
        if name:
            sections.add(name)
    if os.environ.get("MECHCP_MINIMAL", "").strip().lower() in {"1", "true", "yes"}:
        sections.update(_MINIMAL_DISABLED)
    return sections


DISABLED_SECTIONS: set[str] = _initial_disabled_sections()


@asynccontextmanager
async def app_lifespan(server):
    """Manage application lifecycle with proper cleanup."""
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
            persistent_instances = persistent_storage.list_instances()
            if persistent_instances.get("instances"):
                persistent_storage.clear_all()
        except Exception as exc:
            debug_logger.log_error("server", "storage_cleanup", exc)


mcp = FastMCP(
    name="MechCP Browser Automation",
    instructions=(
        "Hardened MCP server providing AI agents Chrome DevTools Protocol level "
        "browser control: navigation, DOM interaction, network interception, "
        "dynamic Python hooks (AST-validated), and full element cloning."
    ),
    lifespan=app_lifespan,
)


# Import the shared singletons + tool registrar after `mcp` exists.
from tools._helpers import browser_manager, network_interceptor
from tools import register_all

register_all(mcp, disabled=DISABLED_SECTIONS)


@mcp.resource("browser://{instance_id}/state")
async def get_browser_state_resource(instance_id: str) -> str:
    """Return the current state of a browser instance as JSON."""
    state = await browser_manager.get_page_state(instance_id)
    if state:
        return json.dumps(state.model_dump(), indent=2, default=str)
    return json.dumps({"error": "Instance not found"})


@mcp.resource("browser://{instance_id}/cookies")
async def get_cookies_resource(instance_id: str) -> str:
    """Return cookies for a browser instance as JSON."""
    tab = await browser_manager.get_tab(instance_id)
    if tab:
        cookies = await network_interceptor.get_cookies(tab)
        return json.dumps(cookies, indent=2)
    return json.dumps({"error": "Instance not found"})


@mcp.resource("browser://{instance_id}/network")
async def get_network_resource(instance_id: str) -> str:
    """Return captured network requests as JSON."""
    requests = await network_interceptor.list_requests(instance_id)
    return json.dumps([req.model_dump() for req in requests], indent=2, default=str)


@mcp.resource("browser://{instance_id}/console")
async def get_console_resource(instance_id: str) -> str:
    """Return console logs for a browser instance as JSON."""
    state = await browser_manager.get_page_state(instance_id)
    if state:
        return json.dumps(state.console_logs, indent=2)
    return json.dumps({"error": "Instance not found"})


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mechcp-server",
        description="MechCP MCP Server with ~85 tools across 11 sections.",
    )
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="Transport protocol to use (default: stdio).",
    )
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("PORT", 8000)),
        help="Port for HTTP transport.",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host for HTTP transport (default: 127.0.0.1).",
    )
    for section in sorted(_ALL_SECTIONS):
        parser.add_argument(
            f"--disable-{section}", action="store_true",
            help=f"Disable the '{section}' tool section.",
        )
    parser.add_argument(
        "--minimal", action="store_true",
        help="Enable only browser-management + element-interaction.",
    )
    parser.add_argument(
        "--list-sections", action="store_true",
        help="List all available tool sections and exit.",
    )
    return parser


def main() -> None:
    args = _build_argparser().parse_args()

    if args.list_sections:
        print("Available tool sections:", file=sys.stderr)
        for section in sorted(_ALL_SECTIONS):
            print(f"  {section}", file=sys.stderr)
        print(
            "\nUse --disable-<section> or set MECHCP_DISABLED_SECTIONS=<csv> to disable sections.",
            file=sys.stderr,
        )
        return

    if args.minimal:
        DISABLED_SECTIONS.update(_MINIMAL_DISABLED)
    for section in _ALL_SECTIONS:
        flag = f"disable_{section.replace('-', '_')}"
        if getattr(args, flag, False):
            DISABLED_SECTIONS.add(section)

    if DISABLED_SECTIONS:
        # Stdio uses stdout for JSON-RPC framing; banners go to stderr.
        print(
            f"Disabled tool sections: {', '.join(sorted(DISABLED_SECTIONS))}",
            file=sys.stderr,
        )

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
