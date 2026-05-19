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

@section_tool("browser-management")
async def spawn_browser(
    headless: bool = False,
    user_agent: Optional[str] = None,
    viewport_width: int = 1920,
    viewport_height: int = 1080,
    proxy: Optional[str] = None,
    block_resources: List[str] = None,
    extra_headers: Dict[str, str] = None,
    user_data_dir: Optional[str] = None,
    sandbox: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Spawn a new browser instance.

    Args:
        headless (bool): Run in headless mode.
        user_agent (Optional[str]): Custom user agent string.
        viewport_width (int): Viewport width in pixels.
        viewport_height (int): Viewport height in pixels.
        proxy (Optional[str]): Proxy server URL.
        block_resources (List[str]): Resource types or URL patterns to block.
            DO NOT block image/font/stylesheet on stealth-sensitive
            navigation: zero image bytes per page is itself a strong bot
            signal. Prefer specific URL patterns (e.g.
            ['*googletagmanager.com*']) over coarse resource-type bans.
        extra_headers (Dict[str, str]): Additional HTTP headers.
        user_data_dir (Optional[str]): Path to user data directory for persistent sessions.
        sandbox (Optional[Any]): Enable browser sandbox. Accepts bool, string ('true'/'false'), int (1/0), or None for auto-detect.

    Returns:
        Dict[str, Any]: Instance information including instance_id.
    """
    try:
        from platform_utils import is_running_as_root, is_running_in_container
        
        if sandbox is None:
            sandbox = not (is_running_as_root() or is_running_in_container())
        elif isinstance(sandbox, str):
            sandbox = sandbox.lower() in ('true', '1', 'yes', 'on', 'enabled')
        elif isinstance(sandbox, int):
            sandbox = bool(sandbox)
        elif not isinstance(sandbox, bool):
            sandbox = bool(sandbox)
        
        options = BrowserOptions(
            headless=headless,
            user_agent=user_agent,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            proxy=proxy,
            block_resources=block_resources or [],
            extra_headers=extra_headers or {},
            user_data_dir=user_data_dir,
            sandbox=sandbox
        )
        instance = await browser_manager.spawn_browser(options)
        tab = await browser_manager.get_tab(instance.instance_id)
        if tab:
            # The dynamic hook interception is already wired up by
            # BrowserManager._setup_dynamic_hooks during spawn_browser; here we
            # only need to enable Network domain capture for the inspector.
            await network_interceptor.setup_interception(
                tab, instance.instance_id, block_resources
            )
        return {
            "instance_id": instance.instance_id,
            "state": instance.state,
            "headless": instance.headless,
            "viewport": instance.viewport
        }
    except Exception as e:
        raise Exception(f"Failed to spawn browser: {str(e)}")

@section_tool("browser-management")
async def list_instances() -> List[Dict[str, Any]]:
    """
    List all active browser instances.

    Returns:
        List[Dict[str, Any]]: List of browser instances with their current state.
    """
    memory_instances = await browser_manager.list_instances()
    storage_instances = persistent_storage.list_instances()
    result = []
    for inst in memory_instances:
        result.append({
            "instance_id": inst.instance_id,
            "state": inst.state,
            "current_url": inst.current_url,
            "title": inst.title,
            "source": "active"
        })
    memory_ids = {inst.instance_id for inst in memory_instances}
    for instance_id, inst_data in storage_instances.get("instances", {}).items():
        if instance_id not in memory_ids:
            result.append({
                "instance_id": inst_data["instance_id"],
                "state": inst_data["state"] + " (stored)",
                "current_url": inst_data["current_url"],
                "title": inst_data["title"],
                "source": "stored"
            })
    return result

@section_tool("browser-management")
async def close_instance(instance_id: str) -> bool:
    """
    Close a browser instance.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        bool: True if closed successfully.
    """
    success = await browser_manager.close_instance(instance_id)
    if success:
        await network_interceptor.clear_instance_data(instance_id)
    return success

@section_tool("browser-management")
async def get_instance_state(instance_id: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed state of a browser instance.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        Optional[Dict[str, Any]]: Complete state information.
    """
    state = await browser_manager.get_page_state(instance_id)
    if state:
        return state.model_dump()
    return None

@section_tool("browser-management")
async def navigate(
    instance_id: str,
    url: str,
    wait_until: str = "load",
    timeout: int = 30000,
    referrer: Optional[str] = None
) -> Dict[str, Any]:
    """
    Navigate to a URL.

    Args:
        instance_id (str): Browser instance ID.
        url (str): URL to navigate to.
        wait_until (str): Wait condition. 'load' (default) waits for the
            window onload event. 'domcontentloaded' waits for the DOM ready
            event. 'networkidle' waits for load + a 500ms quiet window with
            zero in-flight requests, bounded by the navigation timeout.
        timeout (int): Navigation timeout in milliseconds.
        referrer (Optional[str]): If set, attaches as the navigation Referer
            so the target sees Sec-Fetch-Site: same-origin / cross-site
            instead of the "no-history" pattern that flags as direct-bot
            traffic.

    Returns:
        Dict[str, Any]: Navigation result with final URL and title.
    """
    if isinstance(timeout, str):
        timeout = int(timeout)
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    try:
        if referrer:
            try:
                await tab.send(uc.cdp.page.navigate(url=url, referrer=referrer))
            except Exception as exc:
                debug_logger.log_warning(
                    "server",
                    "navigate",
                    f"page.navigate with referrer failed, falling back: {exc}",
                )
                await tab.send(uc.cdp.network.set_extra_http_headers(
                    headers={"Referer": referrer}
                ))
                await tab.get(url)
        else:
            await tab.get(url)
        if wait_until == "domcontentloaded":
            await tab.wait(uc.cdp.page.DomContentEventFired)
        elif wait_until == "networkidle":
            await tab.wait(uc.cdp.page.LoadEventFired)
            settled = await network_interceptor.wait_for_idle(
                instance_id, idle_ms=500, timeout_ms=max(2000, timeout - 1000)
            )
            if not settled:
                debug_logger.log_warning(
                    "server",
                    "navigate",
                    f"network never reached idle within timeout for {url}",
                )
        else:
            await tab.wait(uc.cdp.page.LoadEventFired)
        final_url = await tab.evaluate("window.location.href")
        title = await tab.evaluate("document.title")
        await browser_manager.update_instance_state(instance_id, final_url, title)
        return {
            "url": final_url,
            "title": title,
            "success": True
        }
    except Exception as e:
        raise

@section_tool("browser-management")
async def go_back(instance_id: str) -> bool:
    """
    Navigate back in history.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        bool: True if navigation was successful.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    await tab.back()
    return True

@section_tool("browser-management")
async def go_forward(instance_id: str) -> bool:
    """
    Navigate forward in history.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        bool: True if navigation was successful.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    await tab.forward()
    return True

@section_tool("browser-management")
async def reload_page(instance_id: str, ignore_cache: bool = False) -> bool:
    """
    Reload the current page.

    Args:
        instance_id (str): Browser instance ID.
        ignore_cache (bool): Whether to ignore cache when reloading.

    Returns:
        bool: True if reload was successful.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    await tab.reload()
    return True

@section_tool("element-interaction")
async def query_elements(
    instance_id: str,
    selector: str,
    text_filter: Optional[str] = None,
    visible_only: bool = True,
    limit: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """
    Query DOM elements.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector or XPath (starts with '//').
        text_filter (Optional[str]): Filter by text content.
        visible_only (bool): Only return visible elements.
        limit (Optional[Any]): Maximum number of elements to return.

    Returns:
        List[Dict[str, Any]]: List of matching elements with their properties.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    debug_logger.log_info('Server', 'query_elements', f'Received limit parameter: {limit} (type: {type(limit)})')
    elements = await dom_handler.query_elements(
        tab, selector, text_filter, visible_only, limit
    )
    debug_logger.log_info('Server', 'query_elements', f'DOM handler returned {len(elements)} elements')
    result = []
    for i, elem in enumerate(elements):
        try:
            elem_dict = elem.model_dump() if hasattr(elem, 'model_dump') else dict(elem)
            result.append(elem_dict)
            debug_logger.log_info('Server', 'query_elements', f'Converted element {i+1} to dict: {list(elem_dict.keys())}')
        except Exception as e:
            debug_logger.log_error('Server', 'query_elements', e, {'element_index': i})
    debug_logger.log_info('Server', 'query_elements', f'Returning {len(result)} results to MCP client')
    return result if result else []


@section_tool("element-interaction")
async def query_shadow(
    instance_id: str,
    selector: str,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """Find elements that match a CSS selector, piercing open Shadow DOM.

    Stencil, Lit, Polymer, and modern Web Components (YouTube new UI, parts
    of GitHub, Chrome DevTools) hide their content inside open shadow roots
    that ``query_elements`` cannot see. Use this tool when ``query_elements``
    returns 0 results on a page that visibly contains the element.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector (e.g. ``"button.submit"``).
        max_results (int): Cap on returned matches (default 50).

    Returns:
        List[Dict[str, Any]]: Element snapshots with a ``shadow_path`` field
        that names the host-tag chain leading into the shadow root.
    """
    tab = await browser_manager.get_tab(instance_id)
    if tab is None:
        return []
    return await dom_handler.query_shadow(tab, selector, max_results=max_results)


@section_tool("element-interaction")
async def list_frames(instance_id: str) -> List[Dict[str, Any]]:
    """Enumerate child iframes in the current page.

    Most modern login forms, payment widgets, and reCAPTCHA challenges live
    inside iframes that ``query_elements`` cannot enter. Use this to discover
    the available frames. Per-frame interaction routing is still scaffolding
    today (the ``frame_id`` argument on click/type/wait returns an explicit
    "not yet supported" error); use this tool to inspect iframe URLs and
    surface them to the user instead.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        List[Dict[str, Any]]: ``[{frame_id, url, name, parent_frame_id}]``.
        Empty list when the page has no iframes or the instance is missing.
    """
    tab = await browser_manager.get_tab(instance_id)
    return await dom_handler.list_frames(tab)


@section_tool("element-interaction")
async def click_element(
    instance_id: str,
    selector: str,
    text_match: Optional[str] = None,
    timeout: int = 10000,
    frame_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Click an element and return a post-state verification report.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector or XPath of the element.
        text_match (Optional[str]): Click element with matching text instead.
        timeout (int): Timeout in milliseconds for element resolution.
        frame_id (Optional[str]): If set, target the iframe with this frame_id
            (from ``list_frames``). When omitted, targets the top-level
            document. Per-frame routing is a scaffolding stub today; passing
            a frame_id returns an explicit "not yet supported" error.

    Returns:
        Dict[str, Any]: ``{success, navigated, dom_mutated, url_before,
        url_after, error}``. ``success`` means the click was dispatched;
        ``navigated`` and ``dom_mutated`` show whether anything actually
        changed (the click may have hit an overlay).
    """
    if isinstance(timeout, str):
        timeout = int(timeout)
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {
            "success": False,
            "navigated": False,
            "dom_mutated": False,
            "error": f"Instance not found: {instance_id}",
        }
    resolved = await dom_handler._resolve_frame_tab(tab, frame_id=frame_id)
    if resolved is None:
        return {
            "success": False,
            "navigated": False,
            "dom_mutated": False,
            "error": (
                f"frame_id={frame_id!r} routing not yet supported; "
                "use list_frames to inspect iframes and call on the top-level "
                "document with frame_id=None"
            ),
        }
    return await dom_handler.click_element(resolved, selector, text_match, timeout)

@section_tool("element-interaction")
async def type_text(
    instance_id: str,
    selector: str,
    text: str,
    clear_first: bool = True,
    delay_ms: int = 50,
    parse_newlines: bool = False,
    shift_enter: bool = False,
    frame_id: Optional[str] = None,
) -> bool:
    """Type text into an input field.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector or XPath.
        text (str): Text to type.
        clear_first (bool): Clear field before typing.
        delay_ms (int): Delay between keystrokes in milliseconds.
        parse_newlines (bool): If True, parse \n as Enter key presses.
        shift_enter (bool): If True, use Shift+Enter instead of Enter (for chat apps).
        frame_id (Optional[str]): If set, target the iframe with this
            frame_id. Per-frame routing is a scaffolding stub today; passing
            a frame_id raises an explicit error.

    Returns:
        bool: True if typed successfully.
    """
    if isinstance(delay_ms, str):
        delay_ms = int(delay_ms)
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    resolved = await dom_handler._resolve_frame_tab(tab, frame_id=frame_id)
    if resolved is None:
        raise Exception(
            f"frame_id={frame_id!r} routing not yet supported; "
            "use list_frames to inspect iframes and call without frame_id"
        )
    return await dom_handler.type_text(resolved, selector, text, clear_first, delay_ms, parse_newlines, shift_enter)

@section_tool("element-interaction")
async def paste_text(
    instance_id: str,
    selector: str,
    text: str,
    clear_first: bool = True
) -> bool:
    """
    Paste text instantly into an input field.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector or XPath.
        text (str): Text to paste.
        clear_first (bool): Clear field before pasting.

    Returns:
        bool: True if pasted successfully.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await dom_handler.paste_text(tab, selector, text, clear_first)

@section_tool("element-interaction")
async def select_option(
    instance_id: str,
    selector: str,
    value: Optional[str] = None,
    text: Optional[str] = None,
    index: Optional[Any] = None
) -> bool:
    """
    Select an option from a dropdown.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the select element.
        value (Optional[str]): Option value attribute.
        text (Optional[str]): Option text content.
        index (Optional[Any]): Option index (0-based). Can be string or int.

    Returns:
        bool: True if selected successfully.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    
    converted_index = None
    if index is not None:
        try:
            converted_index = int(index)
        except (ValueError, TypeError):
            raise Exception(f"Invalid index value: {index}. Must be a number.")
    
    return await dom_handler.select_option(tab, selector, value, text, converted_index)

@section_tool("element-interaction")
async def get_element_state(
    instance_id: str,
    selector: str
) -> Dict[str, Any]:
    """
    Get complete state of an element.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector or XPath.

    Returns:
        Dict[str, Any]: Element state including attributes, style, position, etc.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await dom_handler.get_element_state(tab, selector)

@section_tool("element-interaction")
async def wait_for_element(
    instance_id: str,
    selector: str,
    timeout: int = 30000,
    visible: bool = True,
    text_content: Optional[str] = None,
    frame_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Wait for an element to appear (and optionally become visible / contain text).

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector or XPath.
        timeout (int): Timeout in milliseconds.
        visible (bool): Wait for element to be visible.
        text_content (Optional[str]): Wait for specific text content.
        frame_id (Optional[str]): If set, target the iframe with this
            frame_id. Per-frame routing is a scaffolding stub today; passing
            a frame_id raises an explicit error.

    Returns:
        Optional[Dict[str, Any]]: Snapshot ``{tag, id, classes, text, box}``
        when matched, ``None`` on timeout.
    """
    if isinstance(timeout, str):
        timeout = int(timeout)
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    resolved = await dom_handler._resolve_frame_tab(tab, frame_id=frame_id)
    if resolved is None:
        raise Exception(
            f"frame_id={frame_id!r} routing not yet supported; "
            "use list_frames to inspect iframes and call without frame_id"
        )
    return await dom_handler.wait_for_element(resolved, selector, timeout, visible, text_content)

@section_tool("element-interaction")
async def scroll_page(
    instance_id: str,
    direction: str = "down",
    amount: int = 500,
    smooth: bool = True
) -> bool:
    """
    Scroll the page.

    Args:
        instance_id (str): Browser instance ID.
        direction (str): 'down', 'up', 'left', 'right', 'top', or 'bottom'.
        amount (int): Pixels to scroll (ignored for 'top' and 'bottom').
        smooth (bool): Use smooth scrolling.

    Returns:
        bool: True if scrolled successfully.
    """
    if isinstance(amount, str):
        amount = int(amount)
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await dom_handler.scroll_page(tab, direction, amount, smooth)

@section_tool("element-interaction")
async def execute_script(
    instance_id: str,
    script: str,
    args: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """
    Execute JavaScript in page context.

    Args:
        instance_id (str): Browser instance ID.
        script (str): JavaScript code to execute.
        args (Optional[List[Any]]): Arguments to pass to the script.

    Returns:
        Dict[str, Any]: Script execution result.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    try:
        result = await dom_handler.execute_script(tab, script, args)
        return {
            "success": True,
            "result": result,
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": str(e)
        }

@section_tool("element-interaction")
async def get_page_content(
    instance_id: str,
    include_frames: bool = False
) -> Dict[str, Any]:
    """
    Get page HTML and text content.

    Args:
        instance_id (str): Browser instance ID.
        include_frames (bool): Include iframe information.

    Returns:
        Dict[str, Any]: Page content including HTML, text, and metadata.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    content = await dom_handler.get_page_content(tab, include_frames)

    return response_handler.handle_response(
        content,
        "page_content",
        {"instance_id": instance_id, "include_frames": include_frames}
    )


@section_tool("element-interaction")
async def get_visible_text(
    instance_id: str,
    max_chars: int = 4000,
) -> Dict[str, Any]:
    """Return the page's visible innerText, truncated to ``max_chars``.

    Cheap alternative to ``get_page_content`` (which dumps full HTML) and to
    ``take_screenshot`` (which costs tokens to look at). Use this when the
    agent only needs to know "what does the page say".

    Args:
        instance_id (str): Browser instance ID.
        max_chars (int): Hard cap on returned text length (default 4000).

    Returns:
        Dict[str, Any]: ``{url, title, text, truncated, total_length}``.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"url": "", "title": "", "text": "", "truncated": False,
                "error": f"Instance not found: {instance_id}"}
    try:
        url = getattr(tab, "url", "")
        title = await tab.evaluate("document.title")
        text = await tab.evaluate(
            "document.body && document.body.innerText ? document.body.innerText : ''"
        )
        if not isinstance(text, str):
            text = ""
        truncated = len(text) > max_chars
        return {
            "url": url,
            "title": title if isinstance(title, str) else "",
            "text": text[:max_chars],
            "truncated": truncated,
            "total_length": len(text),
        }
    except Exception as e:
        return {"url": "", "title": "", "text": "", "truncated": False, "error": str(e)}


@section_tool("element-interaction")
async def get_page_outline(
    instance_id: str,
) -> Dict[str, Any]:
    """Return a compact outline of headings, landmarks, forms, buttons and links.

    Designed for an agent that needs to navigate or summarize without dumping
    the entire DOM. Returns at most ~200 items across all categories.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        Dict[str, Any]: ``{url, title, headings, landmarks, forms, buttons, links}``.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"error": f"Instance not found: {instance_id}"}
    js = """(() => {
      const lim = (arr, n) => arr.slice(0, n);
      const txt = (el) => ((el.innerText || el.textContent || '').trim().slice(0, 120));
      const headings = lim(
        [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')]
          .filter(h => txt(h))
          .map(h => ({level: parseInt(h.tagName[1]), text: txt(h)})),
        80,
      );
      const landmarks = lim(
        [...document.querySelectorAll('main, nav, header, footer, aside, [role=main], [role=navigation], [role=banner]')]
          .map(el => ({tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || null, label: el.getAttribute('aria-label') || null, id: el.id || null})),
        30,
      );
      const forms = lim(
        [...document.querySelectorAll('form')]
          .map(f => ({action: f.getAttribute('action') || null, method: (f.getAttribute('method') || 'get').toLowerCase(), id: f.id || null, fields: [...f.querySelectorAll('input, select, textarea')].slice(0, 20).map(i => ({name: i.name || null, type: i.type || i.tagName.toLowerCase(), required: i.required, label: (i.labels && i.labels[0] && txt(i.labels[0])) || null}))})),
        15,
      );
      const buttons = lim(
        [...document.querySelectorAll('button, [role=button], input[type=submit], input[type=button]')]
          .map(b => ({text: txt(b) || b.value || null, id: b.id || null, disabled: b.disabled || false})),
        40,
      );
      const links = lim(
        [...document.querySelectorAll('a[href]')]
          .filter(a => txt(a))
          .map(a => ({text: txt(a), href: a.href})),
        50,
      );
      return {
        url: window.location.href,
        title: document.title,
        headings, landmarks, forms, buttons, links,
      };
    })()"""
    try:
        result = await tab.evaluate(js)
        return result if isinstance(result, dict) else {"error": "evaluate returned non-dict"}
    except Exception as e:
        return {"error": str(e)}


@section_tool("element-interaction")
async def take_screenshot(
    instance_id: str,
    full_page: bool = False,
    format: str = "png",
    file_path: Optional[str] = None
) -> Union[str, Dict[str, Any]]:
    """
    Take a screenshot of the page.

    Args:
        instance_id (str): Browser instance ID.
        full_page (bool): Capture full page (not just viewport).
        format (str): Image format ('png' or 'jpeg').
        file_path (Optional[str]): Optional file path to save screenshot to.

    Returns:
        Union[str, Dict]: File path if file_path provided, otherwise optimized base64 data or file info dict.
    """
    from PIL import Image
    import io
    
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    
    if file_path:
        try:
            save_path = safe_join(file_path, allowed_suffixes={".png", ".jpg", ".jpeg"})
        except ValueError as exc:
            return {"success": False, "error": f"unsafe file_path rejected: {exc}"}
        await tab.save_screenshot(save_path)
        return f"Screenshot saved. AI agents should use the Read tool to view this image: {str(save_path.absolute())}"
    
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)
    
    try:
        await tab.save_screenshot(tmp_path)
        
        with Image.open(tmp_path) as img:
            if img.mode in ('RGBA', 'LA', 'P') and format.lower() == 'jpeg':
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            
            output_buffer = io.BytesIO()
            
            if format.lower() == 'jpeg':
                img.save(output_buffer, format='JPEG', quality=85, optimize=True)
            else:
                img.save(output_buffer, format='PNG', optimize=True)
            
            compressed_bytes = output_buffer.getvalue()
            
            base64_size = len(compressed_bytes) * 1.33
            estimated_tokens = int(base64_size / 4)
            
            if estimated_tokens > 20000:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_filename = f"screenshot_{timestamp}_{instance_id[:8]}.{format.lower()}"
                screenshot_path = response_handler.clone_dir / screenshot_filename
                
                with open(screenshot_path, 'wb') as f:
                    f.write(compressed_bytes)
                
                file_size_kb = len(compressed_bytes) / 1024
                return {
                    "file_path": str(screenshot_path),
                    "filename": screenshot_filename,
                    "file_size_kb": round(file_size_kb, 2),
                    "estimated_tokens": estimated_tokens,
                    "reason": "Screenshot too large, automatically saved to file",
                    "message": f"Screenshot saved. AI agents should use the Read tool to view this image: {str(screenshot_path)}"
                }
            
            return base64.b64encode(compressed_bytes).decode('utf-8')
            
    finally:
        if tmp_path.exists():
            os.unlink(tmp_path)


@section_tool("element-interaction")
async def screenshot_element(
    instance_id: str,
    selector: str,
    padding_px: int = 8,
    file_path: Optional[str] = None,
) -> Union[str, Dict[str, Any]]:
    """Screenshot a single element instead of the whole viewport.

    Cheaper than ``take_screenshot`` for UI-state verification (often
    ~10x fewer bytes to look at) since it crops to the element's bounding
    box plus a small padding margin.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector of the target element.
        padding_px (int): Pixels of margin around the element in the capture.
        file_path (Optional[str]): If provided, write the PNG to this path
            (resolved inside the MECHCP_OUTPUT_DIR sandbox). Returns the
            resolved path string. Otherwise returns base64-encoded PNG.

    Returns:
        Union[str, Dict[str, Any]]: Path string or base64 data on success;
        ``{success: False, error}`` on failure.
    """
    import base64 as _b64

    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"success": False, "error": f"Instance not found: {instance_id}"}

    js = (
        "(() => { const el = document.querySelector(%s);"
        " if (!el) return null;"
        " const r = el.getBoundingClientRect();"
        " return {x: r.x, y: r.y, width: r.width, height: r.height,"
        " dpr: window.devicePixelRatio || 1}; })()"
    ) % json.dumps(selector)
    try:
        box = await tab.evaluate(js)
    except Exception as exc:
        return {"success": False, "error": f"could not locate element: {exc}"}
    if not isinstance(box, dict):
        return {"success": False, "error": f"element not found: {selector}"}

    pad = max(0, int(padding_px))
    try:
        clip = uc.cdp.page.Viewport(
            x=max(0.0, float(box["x"]) - pad),
            y=max(0.0, float(box["y"]) - pad),
            width=float(box["width"]) + 2 * pad,
            height=float(box["height"]) + 2 * pad,
            scale=1.0,
        )
        png_b64 = await tab.send(
            uc.cdp.page.capture_screenshot(format_="png", clip=clip)
        )
    except Exception as exc:
        return {"success": False, "error": f"capture_screenshot failed: {exc}"}

    if isinstance(png_b64, tuple):
        png_b64 = png_b64[0]
    if not isinstance(png_b64, str):
        return {"success": False, "error": "capture_screenshot returned no data"}

    if file_path:
        try:
            target = safe_join(file_path, allowed_suffixes={".png"})
        except ValueError as exc:
            return {"success": False, "error": f"unsafe file_path rejected: {exc}"}
        target.write_bytes(_b64.b64decode(png_b64))
        return str(target)
    return png_b64


@section_tool("network-debugging")
async def list_network_requests(
    instance_id: str,
    filter_type: Optional[str] = None
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    List captured network requests.

    Args:
        instance_id (str): Browser instance ID.
        filter_type (Optional[str]): Filter by resource type (e.g., 'image', 'script', 'xhr').

    Returns:
        Union[List[Dict[str, Any]], Dict[str, Any]]: List of network requests, or file metadata if response too large.
    """
    requests = await network_interceptor.list_requests(instance_id, filter_type)
    formatted_requests = [
        {
            "request_id": req.request_id,
            "url": req.url,
            "method": req.method,
            "resource_type": req.resource_type,
            "timestamp": req.timestamp.isoformat()
        }
        for req in requests
    ]
    
    return response_handler.handle_response(formatted_requests, "network_requests")


@section_tool("network-debugging")
async def get_request_details(
    request_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about a network request.

    Args:
        request_id (str): Network request ID.

    Returns:
        Optional[Dict[str, Any]]: Request details including headers, cookies, and body.
    """
    request = await network_interceptor.get_request(request_id)
    if request:
        return request.model_dump()
    return None


@section_tool("network-debugging")
async def get_response_details(
    request_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get response details for a network request.

    Args:
        request_id (str): Network request ID.

    Returns:
        Optional[Dict[str, Any]]: Response details including status, headers, and metadata.
    """
    response = await network_interceptor.get_response(request_id)
    if response:
        return response.model_dump()
    return None


@section_tool("network-debugging")
async def get_response_content(
    instance_id: str,
    request_id: str
) -> Optional[str]:
    """
    Get response body content.

    Args:
        instance_id (str): Browser instance ID.
        request_id (str): Network request ID.

    Returns:
        Optional[str]: Response body as text (base64 encoded for binary).
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    body = await network_interceptor.get_response_body(tab, request_id)
    if body:
        try:
            return body.decode('utf-8')
        except UnicodeDecodeError:
            import base64
            return base64.b64encode(body).decode('utf-8')
    return None


@section_tool("network-debugging")
async def modify_headers(
    instance_id: str,
    headers: Dict[str, str]
) -> bool:
    """
    Modify request headers for future requests.

    Args:
        instance_id (str): Browser instance ID.
        headers (Dict[str, str]): Headers to add/modify.

    Returns:
        bool: True if modified successfully.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await network_interceptor.modify_headers(tab, headers)


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


@section_tool("element-extraction")
async def extract_element_styles(
    instance_id: str,
    selector: str,
    include_computed: bool = True,
    include_css_rules: bool = True,
    include_pseudo: bool = True,
    include_inheritance: bool = False
) -> Dict[str, Any]:
    """
    Extract complete styling information from an element.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_computed (bool): Include computed styles.
        include_css_rules (bool): Include matching CSS rules.
        include_pseudo (bool): Include pseudo-element styles (::before, ::after).
        include_inheritance (bool): Include style inheritance chain.

    Returns:
        Dict[str, Any]: Complete styling data including computed styles, CSS rules, pseudo-elements.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await element_cloner.extract_element_styles(
        tab,
        selector=selector,
        include_computed=include_computed,
        include_css_rules=include_css_rules,
        include_pseudo=include_pseudo,
        include_inheritance=include_inheritance
    )


@section_tool("element-extraction")
async def extract_element_structure(
    instance_id: str,
    selector: str,
    include_children: bool = False,
    include_attributes: bool = True,
    include_data_attributes: bool = True,
    max_depth: int = 3
) -> Dict[str, Any]:
    """
    Extract complete HTML structure and DOM information.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_children (bool): Include child elements.
        include_attributes (bool): Include all attributes.
        include_data_attributes (bool): Include data-* attributes specifically.
        max_depth (int): Maximum depth for children extraction.

    Returns:
        Dict[str, Any]: HTML structure, attributes, position, and children data.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await element_cloner.extract_element_structure(
        tab,
        selector=selector,
        include_children=include_children,
        include_attributes=include_attributes,
        include_data_attributes=include_data_attributes,
        max_depth=max_depth
    )


@section_tool("element-extraction")
async def extract_element_events(
    instance_id: str,
    selector: str,
    include_inline: bool = True,
    include_listeners: bool = True,
    include_framework: bool = True,
    analyze_handlers: bool = False
) -> Dict[str, Any]:
    """
    Extract complete event listener and JavaScript handler information.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_inline (bool): Include inline event handlers (onclick, etc.).
        include_listeners (bool): Include addEventListener attached handlers.
        include_framework (bool): Include framework-specific handlers (React, Vue, etc.).
        analyze_handlers (bool): Analyze handler functions for full details (can be large).

    Returns:
        Dict[str, Any]: Event listeners, inline handlers, framework handlers, detected frameworks.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await element_cloner.extract_element_events(
        tab,
        selector=selector,
        include_inline=include_inline,
        include_listeners=include_listeners,
        include_framework=include_framework,
        analyze_handlers=analyze_handlers
    )


@section_tool("element-extraction")
async def extract_element_animations(
    instance_id: str,
    selector: str,
    include_css_animations: bool = True,
    include_transitions: bool = True,
    include_transforms: bool = True,
    analyze_keyframes: bool = True
) -> Dict[str, Any]:
    """
    Extract CSS animations, transitions, and transforms.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_css_animations (bool): Include CSS @keyframes animations.
        include_transitions (bool): Include CSS transitions.
        include_transforms (bool): Include CSS transforms.
        analyze_keyframes (bool): Analyze keyframe rules.

    Returns:
        Dict[str, Any]: Animation data, transition data, transform data, keyframe rules.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await element_cloner.extract_element_animations(
        tab,
        selector=selector,
        include_css_animations=include_css_animations,
        include_transitions=include_transitions,
        include_transforms=include_transforms,
        analyze_keyframes=analyze_keyframes
    )


@section_tool("element-extraction")
async def extract_element_assets(
    instance_id: str,
    selector: str,
    include_images: bool = True,
    include_backgrounds: bool = True,
    include_fonts: bool = True,
    fetch_external: bool = False
) -> Dict[str, Any]:
    """
    Extract all assets related to an element (images, fonts, etc.).

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_images (bool): Include img src and related images.
        include_backgrounds (bool): Include background images.
        include_fonts (bool): Include font information.
        fetch_external (bool): Whether to fetch external assets for analysis.

    Returns:
        Dict[str, Any]: Images, background images, fonts, icons, videos, audio assets.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    result = await element_cloner.extract_element_assets(
        tab,
        selector=selector,
        include_images=include_images,
        include_backgrounds=include_backgrounds,
        include_fonts=include_fonts,
        fetch_external=fetch_external
    )
    return await response_handler.handle_response(result, f"element_assets_{instance_id}_{selector.replace(' ', '_')}")


@section_tool("element-extraction")
async def extract_element_styles_cdp(
    instance_id: str,
    selector: str,
    include_computed: bool = True,
    include_css_rules: bool = True,
    include_pseudo: bool = True,
    include_inheritance: bool = False,
) -> Dict[str, Any]:
    """
    Extract element styles using direct CDP calls (no JavaScript evaluation).
    This prevents hanging issues by using nodriver's native CDP methods.
    
    Args:
        instance_id (str): Browser instance ID
        selector (str): CSS selector for the element
        include_computed (bool): Include computed styles
        include_css_rules (bool): Include matching CSS rules
        include_pseudo (bool): Include pseudo-element styles
        include_inheritance (bool): Include style inheritance chain
    
    Returns:
        Dict[str, Any]: Styling data extracted using CDP
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await element_cloner.extract_element_styles_cdp(
        tab,
        selector=selector,
        include_computed=include_computed,
        include_css_rules=include_css_rules,
        include_pseudo=include_pseudo,
        include_inheritance=include_inheritance
    )


@section_tool("element-extraction")
async def extract_related_files(
    instance_id: str,
    analyze_css: bool = True,
    analyze_js: bool = True,
    follow_imports: bool = False,
    max_depth: int = 2
) -> Dict[str, Any]:
    """
    Discover and analyze related CSS/JS files for context.

    Args:
        instance_id (str): Browser instance ID.
        analyze_css (bool): Analyze linked CSS files.
        analyze_js (bool): Analyze linked JS files.
        follow_imports (bool): Follow @import and module imports (uses network).
        max_depth (int): Maximum depth for following imports.

    Returns:
        Dict[str, Any]: Stylesheets, scripts, imports, modules, framework detection.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    result = await element_cloner.extract_related_files(
        tab,
        analyze_css=analyze_css,
        analyze_js=analyze_js,
        follow_imports=follow_imports,
        max_depth=max_depth
    )
    return await response_handler.handle_response(result, f"related_files_{instance_id}")


@section_tool("element-extraction")
async def clone_element_complete(
    instance_id: str,
    selector: str,
    extraction_options: Optional[str] = None
) -> Dict[str, Any]:
    """
    Master function that extracts ALL element data using specialized functions.

    This is the ultimate element cloning tool that combines all extraction methods.
    Use this when you want complete element fidelity for recreation or analysis.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        extraction_options (Optional[str]): Dict specifying what to extract and options for each.
            Example: {
                'styles': {'include_computed': True, 'include_pseudo': True},
                'structure': {'include_children': True, 'max_depth': 2},
                'events': {'include_framework': True, 'analyze_handlers': False},
                'animations': {'analyze_keyframes': True},
                'assets': {'fetch_external': False},
                'related_files': {'follow_imports': True, 'max_depth': 1}
            }

    Returns:
        Dict[str, Any]: Complete element clone with styles, structure, events, animations, assets, related files.
    """
    parsed_options = None
    if extraction_options:
        try:
            parsed_options = json.loads(extraction_options)
        except json.JSONDecodeError:
            raise Exception(f"Invalid JSON in extraction_options: {extraction_options}")
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    result = await comprehensive_element_cloner.extract_complete_element(
        tab,
        selector=selector,
        include_children=parsed_options.get('structure', {}).get('include_children', True) if parsed_options else True
    )
    
    return response_handler.handle_response(
        result,
        fallback_filename_prefix="complete_clone",
        metadata={
            "selector": selector,
            "extraction_options": parsed_options,
            "url": getattr(tab, 'url', 'unknown')
        }
    )


@section_tool("progressive-cloning")
async def clone_element_progressive(
    instance_id: str,
    selector: str,
    include_children: bool = True
) -> Dict[str, Any]:
    """
    Clone element progressively - returns lightweight base structure with element_id.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_children (bool): Whether to extract child elements.

    Returns:
        Dict[str, Any]: Base structure with element_id for progressive expansion.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await progressive_element_cloner.clone_element_progressive(tab, selector, include_children)


@section_tool("progressive-cloning")
async def expand_styles(
    element_id: str,
    categories: Optional[List[str]] = None,
    properties: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Expand styles data for a stored element.

    Args:
        element_id (str): Element ID from clone_element_progressive().
        categories (Optional[List[str]]): Style categories to include (layout, typography, colors, spacing, borders, backgrounds, effects, animation).
        properties (Optional[List[str]]): Specific CSS property names to include.

    Returns:
        Dict[str, Any]: Filtered styles data.
    """
    return progressive_element_cloner.expand_styles(element_id, categories, properties)


@section_tool("progressive-cloning")
async def expand_events(
    element_id: str,
    event_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Expand event listeners data for a stored element.

    Args:
        element_id (str): Element ID from clone_element_progressive().
        event_types (Optional[List[str]]): Event types or sources to include (click, react, inline, addEventListener).

    Returns:
        Dict[str, Any]: Filtered event listeners data.
    """
    return progressive_element_cloner.expand_events(element_id, event_types)


@section_tool("progressive-cloning")
async def expand_children(
    element_id: str,
    depth_range: Optional[List] = None,
    max_count: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Expand children data for a stored element.

    Args:
        element_id (str): Element ID from clone_element_progressive().
        depth_range (Optional[List]): [min_depth, max_depth] range to include.
        max_count (Optional[Any]): Maximum number of children to return.

    Returns:
        Dict[str, Any]: Filtered children data.
    """
    if isinstance(max_count, str):
        try:
            max_count = int(max_count) if max_count else None
        except ValueError:
            return {"error": f"Invalid max_count value: {max_count}"}
    
    if isinstance(depth_range, list):
        try:
            depth_range = [int(x) if isinstance(x, str) else x for x in depth_range]
        except ValueError:
            return {"error": f"Invalid depth_range values: {depth_range}"}
    
    depth_tuple = tuple(depth_range) if depth_range else None

    result = progressive_element_cloner.expand_children(element_id, depth_tuple, max_count)
    return response_handler.handle_response(result, f"expand_children_{element_id}")


@section_tool("progressive-cloning")
async def expand_css_rules(
    element_id: str,
    source_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Expand CSS rules data for a stored element.

    Args:
        element_id (str): Element ID from clone_element_progressive().
        source_types (Optional[List[str]]): CSS rule sources to include (inline, external stylesheet URLs).

    Returns:
        Dict[str, Any]: Filtered CSS rules data.
    """
    return progressive_element_cloner.expand_css_rules(element_id, source_types)


@section_tool("progressive-cloning")
async def expand_pseudo_elements(
    element_id: str
) -> Dict[str, Any]:
    """
    Expand pseudo-elements data for a stored element.

    Args:
        element_id (str): Element ID from clone_element_progressive().

    Returns:
        Dict[str, Any]: Pseudo-elements data (::before, ::after, etc.).
    """
    return progressive_element_cloner.expand_pseudo_elements(element_id)


@section_tool("progressive-cloning")
async def expand_animations(
    element_id: str
) -> Dict[str, Any]:
    """
    Expand animations and fonts data for a stored element.

    Args:
        element_id (str): Element ID from clone_element_progressive().

    Returns:
        Dict[str, Any]: Animations, transitions, and fonts data.
    """
    return progressive_element_cloner.expand_animations(element_id)


@section_tool("progressive-cloning")
async def list_stored_elements() -> Dict[str, Any]:
    """
    List all stored elements with their basic info.

    Returns:
        Dict[str, Any]: List of stored elements with metadata.
    """
    return progressive_element_cloner.list_stored_elements()


@section_tool("progressive-cloning")
async def clear_stored_element(
    element_id: str
) -> Dict[str, Any]:
    """
    Clear a specific stored element.

    Args:
        element_id (str): Element ID to clear.

    Returns:
        Dict[str, Any]: Success/error message.
    """
    return progressive_element_cloner.clear_stored_element(element_id)


@section_tool("progressive-cloning")
async def clear_all_elements() -> Dict[str, Any]:
    """
    Clear all stored elements.

    Returns:
        Dict[str, Any]: Success message.
    """
    return progressive_element_cloner.clear_all_elements()


@section_tool("file-extraction")
async def clone_element_to_file(
    instance_id: str,
    selector: str,
    extraction_options: Optional[str] = None
) -> Dict[str, Any]:
    """
    Clone element completely and save to file, returning file path instead of full data.

    This is ideal when you want complete element data but don't want to overwhelm
    the response with large JSON objects. The data is saved to a JSON file that
    can be read later.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        extraction_options (Optional[str]): JSON string with extraction options.

    Returns:
        Dict[str, Any]: File path and summary information about the cloned element.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    parsed_options = None
    if extraction_options:
        try:
            parsed_options = json.loads(extraction_options)
        except json.JSONDecodeError:
            return {"error": "Invalid extraction_options JSON"}
    return await file_based_element_cloner.clone_element_complete_to_file(
        tab, selector=selector, extraction_options=parsed_options
    )


@section_tool("file-extraction")
async def extract_complete_element_to_file(
    instance_id: str,
    selector: str,
    include_children: bool = True
) -> Dict[str, Any]:
    """
    Extract complete element using working comprehensive cloner and save to file.

    This uses the proven comprehensive extraction logic that returns large amounts
    of data, but saves it to a file instead of overwhelming the response.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_children (bool): Whether to include child elements.

    Returns:
        Dict[str, Any]: File path and concise summary instead of massive data dump.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await file_based_element_cloner.extract_complete_element_to_file(
        tab, selector, include_children
    )


@section_tool("element-extraction")
async def extract_complete_element_cdp(
    instance_id: str,
    selector: str,
    include_children: bool = True
) -> Dict[str, Any]:
    """
    Extract complete element using native CDP methods for 100% accuracy.

    This uses Chrome DevTools Protocol's native methods to extract:
    - Complete computed styles via CSS.getComputedStyleForNode
    - Matched CSS rules via CSS.getMatchedStylesForNode  
    - Event listeners via DOMDebugger.getEventListeners
    - Complete DOM structure and attributes

    This provides the most accurate element cloning possible by bypassing
    JavaScript limitations and using CDP's direct browser access.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_children (bool): Whether to include child elements.

    Returns:
        Dict[str, Any]: Complete element data with 100% accuracy.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    cdp_cloner = CDPElementCloner()
    return await cdp_cloner.extract_complete_element_cdp(tab, selector, include_children)


@section_tool("file-extraction")
async def extract_element_styles_to_file(
    instance_id: str,
    selector: str,
    include_computed: bool = True,
    include_css_rules: bool = True,
    include_pseudo: bool = True,
    include_inheritance: bool = False
) -> Dict[str, Any]:
    """
    Extract element styles and save to file, returning file path.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_computed (bool): Include computed styles.
        include_css_rules (bool): Include matching CSS rules.
        include_pseudo (bool): Include pseudo-element styles.
        include_inheritance (bool): Include style inheritance chain.

    Returns:
        Dict[str, Any]: File path and summary of extracted styles.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await file_based_element_cloner.extract_element_styles_to_file(
        tab,
        selector=selector,
        include_computed=include_computed,
        include_css_rules=include_css_rules,
        include_pseudo=include_pseudo,
        include_inheritance=include_inheritance
    )


@section_tool("file-extraction")
async def extract_element_structure_to_file(
    instance_id: str,
    selector: str,
    include_children: bool = False,
    include_attributes: bool = True,
    include_data_attributes: bool = True,
    max_depth: int = 3
) -> Dict[str, Any]:
    """
    Extract element structure and save to file, returning file path.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_children (bool): Include child elements.
        include_attributes (bool): Include all attributes.
        include_data_attributes (bool): Include data-* attributes.
        max_depth (int): Maximum depth for children extraction.

    Returns:
        Dict[str, Any]: File path and summary of extracted structure.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await file_based_element_cloner.extract_element_structure_to_file(
        tab,
        selector=selector,
        include_children=include_children,
        include_attributes=include_attributes,
        include_data_attributes=include_data_attributes,
        max_depth=max_depth
    )


@section_tool("file-extraction")
async def extract_element_events_to_file(
    instance_id: str,
    selector: str,
    include_inline: bool = True,
    include_listeners: bool = True,
    include_framework: bool = True,
    analyze_handlers: bool = True
) -> Dict[str, Any]:
    """
    Extract element events and save to file, returning file path.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_inline (bool): Include inline event handlers.
        include_listeners (bool): Include addEventListener handlers.
        include_framework (bool): Include framework-specific handlers.
        analyze_handlers (bool): Analyze handler functions.

    Returns:
        Dict[str, Any]: File path and summary of extracted events.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await file_based_element_cloner.extract_element_events_to_file(
        tab,
        selector=selector,
        include_inline=include_inline,
        include_listeners=include_listeners,
        include_framework=include_framework,
        analyze_handlers=analyze_handlers
    )


@section_tool("file-extraction")
async def extract_element_animations_to_file(
    instance_id: str,
    selector: str,
    include_css_animations: bool = True,
    include_transitions: bool = True,
    include_transforms: bool = True,
    analyze_keyframes: bool = True
) -> Dict[str, Any]:
    """
    Extract element animations and save to file, returning file path.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_css_animations (bool): Include CSS animations.
        include_transitions (bool): Include CSS transitions.
        include_transforms (bool): Include CSS transforms.
        analyze_keyframes (bool): Analyze keyframe rules.

    Returns:
        Dict[str, Any]: File path and summary of extracted animations.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await file_based_element_cloner.extract_element_animations_to_file(
        tab,
        selector=selector,
        include_css_animations=include_css_animations,
        include_transitions=include_transitions,
        include_transforms=include_transforms,
        analyze_keyframes=analyze_keyframes
    )


@section_tool("file-extraction")
async def extract_element_assets_to_file(
    instance_id: str,
    selector: str,
    include_images: bool = True,
    include_backgrounds: bool = True,
    include_fonts: bool = True,
    fetch_external: bool = False
) -> Dict[str, Any]:
    """
    Extract element assets and save to file, returning file path.

    Args:
        instance_id (str): Browser instance ID.
        selector (str): CSS selector for the element.
        include_images (bool): Include images.
        include_backgrounds (bool): Include background images.
        include_fonts (bool): Include font information.
        fetch_external (bool): Fetch external assets.

    Returns:
        Dict[str, Any]: File path and summary of extracted assets.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        raise Exception(f"Instance not found: {instance_id}")
    return await file_based_element_cloner.extract_element_assets_to_file(
        tab,
        selector=selector,
        include_images=include_images,
        include_backgrounds=include_backgrounds,
        include_fonts=include_fonts,
        fetch_external=fetch_external
    )


@section_tool("file-extraction")
async def list_clone_files() -> List[Dict[str, Any]]:
    """
    List all element clone files saved to disk.

    Returns:
        List[Dict[str, Any]]: List of clone files with metadata and file information.
    """
    return file_based_element_cloner.list_clone_files()


@section_tool("file-extraction")
async def cleanup_clone_files(
    max_age_hours: int = 24
) -> Dict[str, int]:
    """
    Clean up old clone files to save disk space.

    Args:
        max_age_hours (int): Maximum age in hours for files to keep.

    Returns:
        Dict[str, int]: Number of files deleted.
    """
    deleted_count = file_based_element_cloner.cleanup_old_files(max_age_hours)
    return {"deleted_count": deleted_count}


@section_tool("cdp-functions")
async def list_cdp_commands() -> List[str]:
    """
    List all available CDP Runtime commands for function execution.

    Returns:
        List[str]: List of available CDP command names.
    """
    return await cdp_function_executor.list_cdp_commands()


@section_tool("cdp-functions")
async def execute_cdp_command(
    instance_id: str,
    command: str,
    params: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Execute any CDP Runtime command with given parameters.

    Args:
        instance_id (str): Browser instance ID.
        command (str): CDP command name (e.g., 'evaluate', 'callFunctionOn').
        params (Dict[str, Any], optional): Command parameters as a dictionary.
                IMPORTANT: Use snake_case parameter names (e.g., 'return_by_value') 
                NOT camelCase ('returnByValue'). The nodriver library expects 
                Python-style parameter names.

    Returns:
        Dict[str, Any]: Command execution result.
        
    Example:
        # Correct - use snake_case
        params = {"expression": "document.title", "return_by_value": True}
        
        params = {"expression": "document.title", "returnByValue": True}
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"success": False, "error": f"Instance not found: {instance_id}"}
    return await cdp_function_executor.execute_cdp_command(tab, command, params or {})


@section_tool("cdp-functions")
async def get_execution_contexts(
    instance_id: str
) -> List[Dict[str, Any]]:
    """
    Get all available JavaScript execution contexts.

    Args:
        instance_id (str): Browser instance ID.

    Returns:
        List[Dict[str, Any]]: List of execution contexts with their details.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return []
    contexts = await cdp_function_executor.get_execution_contexts(tab)
    return [
        {
            "id": ctx.id,
            "name": ctx.name,
            "origin": ctx.origin,
            "unique_id": ctx.unique_id,
            "aux_data": ctx.aux_data
        }
        for ctx in contexts
    ]


@section_tool("cdp-functions")
async def discover_global_functions(
    instance_id: str,
    context_id: str = None
) -> List[Dict[str, Any]]:
    """
    Discover all global JavaScript functions available in the page.

    Args:
        instance_id (str): Browser instance ID.
        context_id (str, optional): Optional execution context ID.

    Returns:
        List[Dict[str, Any]]: List of discovered functions with their details.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return []
    functions = await cdp_function_executor.discover_global_functions(tab, context_id)
    result = [
        {
            "name": func.name,
            "path": func.path,
            "signature": func.signature,
            "description": func.description
        }
        for func in functions
    ]
    
    file_response = response_handler.handle_response(
        result,
        fallback_filename_prefix="global_functions",
        metadata={
            "context_id": context_id,
            "function_count": len(result),
            "url": getattr(tab, 'url', 'unknown')
        }
    )
    
    if isinstance(file_response, dict) and "file_path" in file_response:
        return [{
            "name": "LARGE_RESPONSE_SAVED_TO_FILE",
            "path": "file_storage",
            "signature": "automatic_file_fallback",
            "description": f"Response too large ({file_response['estimated_tokens']} tokens), saved to: {file_response['filename']}"
        }]
    
    return file_response


@section_tool("cdp-functions")
async def discover_object_methods(
    instance_id: str,
    object_path: str
) -> List[Dict[str, Any]]:
    """
    Discover methods of a specific JavaScript object.

    Args:
        instance_id (str): Browser instance ID.
        object_path (str): Path to the object (e.g., 'document', 'window.localStorage').

    Returns:
        List[Dict[str, Any]]: List of discovered methods.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return []
    methods = await cdp_function_executor.discover_object_methods(tab, object_path)
    methods_data = [
        {
            "name": method.name,
            "path": method.path,
            "signature": method.signature,
            "description": method.description
        }
        for method in methods
    ]
    
    return await response_handler.handle_response(
        methods_data,
        f"object_methods_{object_path.replace('.', '_')}"
    )


@section_tool("cdp-functions")
async def call_javascript_function(
    instance_id: str,
    function_path: str,
    args: List[Any] = None
) -> Dict[str, Any]:
    """
    Call a JavaScript function with arguments.

    Args:
        instance_id (str): Browser instance ID.
        function_path (str): Full path to the function (e.g., 'document.getElementById').
        args (List[Any], optional): List of arguments to pass to the function.

    Returns:
        Dict[str, Any]: Function call result.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"success": False, "error": f"Instance not found: {instance_id}"}
    return await cdp_function_executor.call_discovered_function(tab, function_path, args or [])


@section_tool("cdp-functions")
async def inspect_function_signature(
    instance_id: str,
    function_path: str
) -> Dict[str, Any]:
    """
    Inspect a JavaScript function's signature and details.

    Args:
        instance_id (str): Browser instance ID.
        function_path (str): Full path to the function.

    Returns:
        Dict[str, Any]: Function signature and details.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"success": False, "error": f"Instance not found: {instance_id}"}
    return await cdp_function_executor.inspect_function_signature(tab, function_path)


@section_tool("cdp-functions")
async def inject_and_execute_script(
    instance_id: str,
    script_code: str,
    context_id: str = None
) -> Dict[str, Any]:
    """
    Inject and execute custom JavaScript code.

    Args:
        instance_id (str): Browser instance ID.
        script_code (str): JavaScript code to execute.
        context_id (str, optional): Optional execution context ID.

    Returns:
        Dict[str, Any]: Script execution result.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"success": False, "error": f"Instance not found: {instance_id}"}
    return await cdp_function_executor.inject_and_execute_script(tab, script_code, context_id)


@section_tool("cdp-functions")
async def create_persistent_function(
    instance_id: str,
    function_name: str,
    function_code: str
) -> Dict[str, Any]:
    """
    Create a persistent JavaScript function that survives page reloads.

    Args:
        instance_id (str): Browser instance ID.
        function_name (str): Name for the function.
        function_code (str): JavaScript function code.

    Returns:
        Dict[str, Any]: Function creation result.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"success": False, "error": f"Instance not found: {instance_id}"}
    return await cdp_function_executor.create_persistent_function(tab, function_name, function_code, instance_id)


@section_tool("cdp-functions")
async def execute_function_sequence(
    instance_id: str,
    function_calls: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Execute a sequence of JavaScript function calls.

    Args:
        instance_id (str): Browser instance ID.
        function_calls (List[Dict[str, Any]]): List of function calls, each with 'function_path', 'args', and optional 'context_id'.

    Returns:
        List[Dict[str, Any]]: List of function call results.
    """
    from cdp_function_executor import FunctionCall
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return [{"success": False, "error": f"Instance not found: {instance_id}"}]
    calls = []
    for call_data in function_calls:
        calls.append(FunctionCall(
            function_path=call_data['function_path'],
            args=call_data.get('args', []),
            context_id=call_data.get('context_id')
        ))
    return await cdp_function_executor.execute_function_sequence(tab, calls)


@section_tool("cdp-functions")
async def create_python_binding(
    instance_id: str,
    binding_name: str,
    python_code: str
) -> Dict[str, Any]:
    """
    Create a binding that allows JavaScript to call Python functions.

    Args:
        instance_id (str): Browser instance ID.
        binding_name (str): Name for the binding.
        python_code (str): Python function code (as string).

    Returns:
        Dict[str, Any]: Binding creation result.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"success": False, "error": f"Instance not found: {instance_id}"}
    try:
        exec_globals = safe_compile(
            python_code,
            filename=f"<binding:{binding_name}>",
        )
        python_function = next(
            (
                obj
                for name, obj in exec_globals.items()
                if callable(obj) and not name.startswith("_") and name != "HookAction"
            ),
            None,
        )
        if not python_function:
            return {"success": False, "error": "No callable function defined in python_code"}
        return await cdp_function_executor.create_python_binding(tab, binding_name, python_function)
    except PermissionError as e:
        return {
            "success": False,
            "error": f"python_code rejected by safe-code validator: {e}",
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to create Python function: {str(e)}"}


@section_tool("cdp-functions")
async def execute_python_in_browser(
    instance_id: str,
    python_code: str
) -> Dict[str, Any]:
    """
    Execute Python code by translating it to JavaScript.

    Args:
        instance_id (str): Browser instance ID.
        python_code (str): Python code to translate and execute.

    Returns:
        Dict[str, Any]: Execution result.
    """
    tab = await browser_manager.get_tab(instance_id)
    if not tab:
        return {"success": False, "error": f"Instance not found: {instance_id}"}
    return await cdp_function_executor.execute_python_in_browser(tab, python_code)


@section_tool("cdp-functions")
async def get_function_executor_info(
    instance_id: str = None
) -> Dict[str, Any]:
    """
    Get information about the CDP function executor state.

    Args:
        instance_id (str, optional): Optional browser instance ID for specific info.

    Returns:
        Dict[str, Any]: Function executor state and capabilities.
    """
    return await cdp_function_executor.get_function_executor_info(instance_id)


@section_tool("dynamic-hooks")
async def create_dynamic_hook(
    name: str,
    requirements: Dict[str, Any],
    function_code: str,
    instance_ids: Optional[List[str]] = None,
    priority: int = 100
) -> Dict[str, Any]:
    """
    Create a new dynamic hook with AI-generated Python function.
    
    This is the new powerful hook system that allows AI to write custom Python functions
    that process network requests in real-time with no pending state.
    
    Args:
        name (str): Human-readable hook name
        requirements (Dict[str, Any]): Matching criteria (url_pattern, method, resource_type, custom_condition)
        function_code (str): Python function code that processes requests (must define process_request(request))
        instance_ids (Optional[List[str]]): Browser instances to apply hook to (all if None)
        priority (int): Hook priority (lower = higher priority)
        
    Returns:
        Dict[str, Any]: Hook creation result with hook_id
        
    Example function_code:
        ```python
        def process_request(request):
            if "example.com" in request["url"]:
                return HookAction(action="redirect", url="https://httpbin.org/get")
            return HookAction(action="continue")
        ```
    """
    result = await dynamic_hook_ai.create_dynamic_hook(
        name=name,
        requirements=requirements,
        function_code=function_code,
        instance_ids=instance_ids,
        priority=priority
    )

    # Lazy Fetch.enable: when the first hook lands on an instance, the
    # interception was deferred at spawn time for stealth. Re-run setup so
    # Fetch domain becomes active for the affected tabs.
    if isinstance(result, dict) and result.get("success"):
        target_ids = instance_ids or list(dynamic_hook_system.instance_hooks.keys())
        for inst_id in target_ids:
            tab = await browser_manager.get_tab(inst_id)
            if tab is not None:
                try:
                    await dynamic_hook_system.setup_interception(tab, inst_id)
                except Exception as exc:
                    debug_logger.log_warning(
                        "server",
                        "create_dynamic_hook",
                        f"re-setup interception failed for {inst_id}: {exc}",
                    )
    return result


@section_tool("dynamic-hooks")
async def create_simple_dynamic_hook(
    name: str,
    url_pattern: str,
    action: str,
    target_url: Optional[str] = None,
    custom_headers: Optional[Dict[str, str]] = None,
    instance_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Create a simple dynamic hook using predefined templates (easier for AI).
    
    Args:
        name (str): Hook name
        url_pattern (str): URL pattern to match
        action (str): Action type - 'block', 'redirect', 'add_headers', or 'log'
        target_url (Optional[str]): Target URL for redirect action
        custom_headers (Optional[Dict[str, str]]): Headers to add for add_headers action
        instance_ids (Optional[List[str]]): Browser instances to apply hook to
        
    Returns:
        Dict[str, Any]: Hook creation result
    """
    return await dynamic_hook_ai.create_simple_hook(
        name=name,
        url_pattern=url_pattern,
        action=action,
        target_url=target_url,
        custom_headers=custom_headers,
        instance_ids=instance_ids
    )


@section_tool("dynamic-hooks")
async def list_dynamic_hooks(instance_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List all dynamic hooks.
    
    Args:
        instance_id (Optional[str]): Optional filter by browser instance
        
    Returns:
        Dict[str, Any]: List of hooks with details and statistics
    """
    return await dynamic_hook_ai.list_dynamic_hooks(instance_id=instance_id)


@section_tool("dynamic-hooks")
async def get_dynamic_hook_details(hook_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific dynamic hook.
    
    Args:
        hook_id (str): Hook identifier
        
    Returns:
        Dict[str, Any]: Detailed hook information including function code
    """
    return await dynamic_hook_ai.get_hook_details(hook_id=hook_id)


@section_tool("dynamic-hooks")
async def remove_dynamic_hook(hook_id: str) -> Dict[str, Any]:
    """
    Remove a dynamic hook.
    
    Args:
        hook_id (str): Hook identifier to remove
        
    Returns:
        Dict[str, Any]: Removal status
    """
    return await dynamic_hook_ai.remove_dynamic_hook(hook_id=hook_id)


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