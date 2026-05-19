"""Main MCP server for browser automation."""

import asyncio
import base64
import importlib
import json
import os
import signal
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import nodriver as uc
from fastmcp import FastMCP

from browser_manager import BrowserManager
from cdp_function_executor import CDPFunctionExecutor
from cloner import (
    CDPElementCloner,
    comprehensive_element_cloner,
    element_cloner,
    file_based_element_cloner,
    progressive_element_cloner,
)
from debug_logger import debug_logger
from dom_handler import DOMHandler
from models import (
    BrowserOptions,
    NavigationOptions,
    ScriptResult,
    BrowserState,
    PageState,
)
from network_interceptor import NetworkInterceptor
from dynamic_hook_system import dynamic_hook_system
from dynamic_hook_ai_interface import dynamic_hook_ai
from persistent_storage import persistent_storage
from response_handler import response_handler
from platform_utils import validate_browser_environment, get_platform_info
from process_cleanup import process_cleanup
from path_safety import safe_join, sanitize_filename
from safe_code import safe_compile

def _initial_disabled_sections() -> set:
    """Compute the initial disabled-section set before any @section_tool runs.

    Reads MECHCP_DISABLED_SECTIONS (comma-separated section names) and a
    boolean MECHCP_MINIMAL flag. Argparse later in __main__ can still extend
    the set, but the import-time set covers the cold-start optimization case
    where the operator sets the env var in their MCP client config.
    """
    sections: set = set()
    raw = os.environ.get("MECHCP_DISABLED_SECTIONS", "")
    for name in raw.split(","):
        name = name.strip()
        if name:
            sections.add(name)
    if os.environ.get("MECHCP_MINIMAL", "").strip().lower() in {"1", "true", "yes"}:
        sections.update({
            "element-extraction", "file-extraction", "network-debugging",
            "cdp-functions", "progressive-cloning", "cookies-storage",
            "tabs", "debugging", "dynamic-hooks",
        })
    return sections


DISABLED_SECTIONS: set = _initial_disabled_sections()

def is_section_enabled(section: str) -> bool:
    """Check if a tool section is enabled."""
    return section not in DISABLED_SECTIONS

def section_tool(section: str):
    """Decorator to conditionally register tools based on section status."""
    def decorator(func):
        if is_section_enabled(section):
            return mcp.tool(func)
        else:
            return func
    return decorator

@asynccontextmanager
async def app_lifespan(server):
    """
    Manage application lifecycle with proper cleanup.

    Args:
        server (Any): The server instance for which the lifespan is being managed.
    """
    debug_logger.log_info("server", "startup", "Starting Browser Automation MCP Server...")
    try:
        yield
    finally:
        debug_logger.log_info("server", "shutdown", "Shutting down Browser Automation MCP Server...")
        try:
            await browser_manager.close_all()
            debug_logger.log_info("server", "cleanup", "All browser instances closed")
        except Exception as e:
            debug_logger.log_error("server", "cleanup", e)
        
        try:
            process_cleanup._cleanup_all_tracked()
            debug_logger.log_info("server", "cleanup", "Process cleanup complete")
        except Exception as e:
            debug_logger.log_error("server", "cleanup", f"Process cleanup failed: {e}")
        try:
            persistent_instances = persistent_storage.list_instances()
            if persistent_instances.get("instances"):
                debug_logger.log_info(
                    "server",
                    "storage_cleanup",
                    f"Clearing in-memory storage with {len(persistent_instances['instances'])} instances...",
                )
                persistent_storage.clear_all()
                debug_logger.log_info("server", "storage_cleanup", "In-memory storage cleared")
        except Exception as e:
            debug_logger.log_error("server", "storage_cleanup", e)
        debug_logger.log_info("server", "shutdown", "Browser Automation MCP Server shutdown complete")

mcp = FastMCP(
    name="Browser Automation MCP",
    instructions="""
    This MCP server provides undetectable browser automation using nodriver (CDP-based).
    
    Key features:
    - Spawn and manage multiple browser instances
    - Navigate and interact with web pages
    - Query and manipulate DOM elements
    - Intercept and analyze network traffic
    - Execute JavaScript in page context
    - Manage cookies and storage
    
    All browser instances are undetectable by anti-bot systems.
    """,
    lifespan=app_lifespan,
)

from tools._helpers import (
    browser_manager,
    cdp_function_executor,
    dom_handler,
    element_cloner as _shared_element_cloner,
    network_interceptor,
)
from tools import register_all

# Re-bind the cloner alias used throughout server.py to the shared singleton
# so tools migrated to tools/* and tools still in server.py refer to the
# same instance.
element_cloner = _shared_element_cloner

register_all(mcp)

@mcp.resource("browser://{instance_id}/state")
async def get_browser_state_resource(instance_id: str) -> str:
    """
    Get current state of a browser instance.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        str: JSON string of the browser state or error message.
    """
    state = await browser_manager.get_page_state(instance_id)
    if state:
        return json.dumps(state.model_dump(), indent=2, default=str)
    return json.dumps({"error": "Instance not found"})


@mcp.resource("browser://{instance_id}/cookies")
async def get_cookies_resource(instance_id: str) -> str:
    """
    Get cookies for a browser instance.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        str: JSON string of cookies or error message.
    """
    tab = await browser_manager.get_tab(instance_id)
    if tab:
        cookies = await network_interceptor.get_cookies(tab)
        return json.dumps(cookies, indent=2)
    return json.dumps({"error": "Instance not found"})


@mcp.resource("browser://{instance_id}/network")
async def get_network_resource(instance_id: str) -> str:
    """
    Get network requests for a browser instance.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        str: JSON string of network requests.
    """
    requests = await network_interceptor.list_requests(instance_id)
    return json.dumps([req.model_dump() for req in requests], indent=2, default=str)


@mcp.resource("browser://{instance_id}/console")
async def get_console_resource(instance_id: str) -> str:
    """
    Get console logs for a browser instance.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        str: JSON string of console logs or error message.
    """
    state = await browser_manager.get_page_state(instance_id)
    if state:
        return json.dumps(state.console_logs, indent=2)
    return json.dumps({"error": "Instance not found"})


@section_tool("dynamic-hooks")
def get_hook_documentation() -> Dict[str, Any]:
    """
    Get comprehensive documentation for creating hook functions (AI learning).
    
    Returns:
        Dict[str, Any]: Documentation of request object structure and HookAction types
    """
    return dynamic_hook_ai.get_request_documentation()


@section_tool("dynamic-hooks")
def get_hook_examples() -> Dict[str, Any]:
    """
    Get example hook functions for AI learning.
    
    Returns:
        Dict[str, Any]: Collection of example hook functions with explanations
    """
    return dynamic_hook_ai.get_hook_examples()


@section_tool("dynamic-hooks")
def get_hook_requirements_documentation() -> Dict[str, Any]:
    """
    Get documentation on hook requirements and matching criteria.
    
    Returns:
        Dict[str, Any]: Requirements documentation and best practices
    """
    return dynamic_hook_ai.get_requirements_documentation()


@section_tool("dynamic-hooks")
def get_hook_common_patterns() -> Dict[str, Any]:
    """
    Get common hook patterns and use cases.
    
    Returns:
        Dict[str, Any]: Common patterns like ad blocking, API proxying, etc.
    """
    return dynamic_hook_ai.get_common_patterns()


@section_tool("dynamic-hooks")
def validate_hook_function(function_code: str) -> Dict[str, Any]:
    """
    Validate hook function code for common issues before creating.
    
    Args:
        function_code (str): Python function code to validate
        
    Returns:
        Dict[str, Any]: Validation results with issues and warnings
    """
    return dynamic_hook_ai.validate_hook_function(function_code=function_code)



if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Stealth Browser MCP Server with 90 tools")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                      help="Transport protocol to use")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8000)),
                      help="Port for HTTP transport")
    parser.add_argument("--host", default="0.0.0.0",
                      help="Host for HTTP transport")
    
    parser.add_argument("--disable-browser-management", action="store_true",
                      help="Disable browser management tools (spawn, navigate, close, etc.)")
    parser.add_argument("--disable-element-interaction", action="store_true",
                      help="Disable element interaction tools (click, type, scroll, etc.)")
    parser.add_argument("--disable-element-extraction", action="store_true",
                      help="Disable element extraction tools (styles, structure, events, etc.)")
    parser.add_argument("--disable-file-extraction", action="store_true",
                      help="Disable file-based extraction tools")
    parser.add_argument("--disable-network-debugging", action="store_true",
                      help="Disable network debugging and interception tools")
    parser.add_argument("--disable-cdp-functions", action="store_true",
                      help="Disable CDP function execution tools")
    parser.add_argument("--disable-progressive-cloning", action="store_true",
                      help="Disable progressive element cloning tools")
    parser.add_argument("--disable-cookies-storage", action="store_true",
                      help="Disable cookie and storage management tools")
    parser.add_argument("--disable-tabs", action="store_true",
                      help="Disable tab management tools")
    parser.add_argument("--disable-debugging", action="store_true",
                      help="Disable debug and system tools")
    parser.add_argument("--disable-dynamic-hooks", action="store_true",
                      help="Disable dynamic network hook system")
    
    parser.add_argument("--minimal", action="store_true",
                      help="Enable only core browser management and element interaction (disable everything else)")
    parser.add_argument("--list-sections", action="store_true",
                      help="List all available tool sections and exit")
    
    args = parser.parse_args()
    
    if args.list_sections:
        print("Available tool sections:")
        print("  browser-management: Core browser operations (11 tools)")
        print("  element-interaction: Page interaction and element manipulation (8 tools)")
        print("  element-extraction: Element cloning and extraction (10 tools)")
        print("  file-extraction: File-based extraction tools (9 tools)")
        print("  network-debugging: Network monitoring and interception (10 tools)")
        print("  cdp-functions: Chrome DevTools Protocol function execution (15 tools)")
        print("  progressive-cloning: Advanced element cloning system (10 tools)")
        print("  cookies-storage: Cookie and storage management (3 tools)")
        print("  tabs: Tab management (5 tools)")
        print("  debugging: Debug and system tools (6 tools)")
        print("  dynamic-hooks: AI-powered network hook system (12 tools)")
        print("\nUse --disable-<section-name> to disable specific sections")
        print("Use --minimal to enable only core functionality")
        sys.exit(0)
    
    if args.minimal:
        DISABLED_SECTIONS.update([
            "element-extraction", "file-extraction", "network-debugging",
            "cdp-functions", "progressive-cloning", "cookies-storage",
            "tabs", "debugging", "dynamic-hooks"
        ])
    
    if args.disable_browser_management:
        DISABLED_SECTIONS.add("browser-management")
    if args.disable_element_interaction:
        DISABLED_SECTIONS.add("element-interaction")
    if args.disable_element_extraction:
        DISABLED_SECTIONS.add("element-extraction")
    if args.disable_file_extraction:
        DISABLED_SECTIONS.add("file-extraction")
    if args.disable_network_debugging:
        DISABLED_SECTIONS.add("network-debugging")
    if args.disable_cdp_functions:
        DISABLED_SECTIONS.add("cdp-functions")
    if args.disable_progressive_cloning:
        DISABLED_SECTIONS.add("progressive-cloning")
    if args.disable_cookies_storage:
        DISABLED_SECTIONS.add("cookies-storage")
    if args.disable_tabs:
        DISABLED_SECTIONS.add("tabs")
    if args.disable_debugging:
        DISABLED_SECTIONS.add("debugging")
    if args.disable_dynamic_hooks:
        DISABLED_SECTIONS.add("dynamic-hooks")
    
    if DISABLED_SECTIONS:
        # Stdio transports use stdout for JSON-RPC framing; banners go to stderr.
        print(f"Disabled tool sections: {', '.join(sorted(DISABLED_SECTIONS))}", file=sys.stderr)
    
    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")