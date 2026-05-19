"""Browser-management MCP tools: spawn/list/close, navigate, history, reload."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import nodriver as uc
from fastmcp import FastMCP

from debug_logger import debug_logger
from models import BrowserOptions
from persistent_storage import persistent_storage

from ._helpers import browser_manager, network_interceptor, section_tool


def register(mcp: FastMCP) -> None:
    @section_tool(mcp, "browser-management")
    async def spawn_browser(
        headless: bool = False,
        user_agent: Optional[str] = None,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
        proxy: Optional[str] = None,
        block_resources: List[str] = None,
        extra_headers: Dict[str, str] = None,
        user_data_dir: Optional[str] = None,
        sandbox: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Spawn a new browser instance.

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
            sandbox (Optional[Any]): Enable browser sandbox. Accepts bool, string,
                int, or None for auto-detect.

        Returns:
            Dict[str, Any]: Instance information including instance_id.
        """
        try:
            from platform_utils import is_running_as_root, is_running_in_container

            if sandbox is None:
                sandbox = not (is_running_as_root() or is_running_in_container())
            elif isinstance(sandbox, str):
                sandbox = sandbox.lower() in ("true", "1", "yes", "on", "enabled")
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
                sandbox=sandbox,
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
                "viewport": instance.viewport,
            }
        except Exception as e:
            raise Exception(f"Failed to spawn browser: {str(e)}") from e

    @section_tool(mcp, "browser-management")
    async def list_instances() -> List[Dict[str, Any]]:
        """List all active browser instances."""
        memory_instances = await browser_manager.list_instances()
        storage_instances = persistent_storage.list_instances()
        result = []
        for inst in memory_instances:
            result.append({
                "instance_id": inst.instance_id,
                "state": inst.state,
                "current_url": inst.current_url,
                "title": inst.title,
                "source": "active",
            })
        memory_ids = {inst.instance_id for inst in memory_instances}
        for instance_id, inst_data in storage_instances.get("instances", {}).items():
            if instance_id not in memory_ids:
                result.append({
                    "instance_id": inst_data["instance_id"],
                    "state": inst_data["state"] + " (stored)",
                    "current_url": inst_data["current_url"],
                    "title": inst_data["title"],
                    "source": "stored",
                })
        return result

    @section_tool(mcp, "browser-management")
    async def close_instance(instance_id: str) -> bool:
        """Close a browser instance."""
        success = await browser_manager.close_instance(instance_id)
        if success:
            await network_interceptor.clear_instance_data(instance_id)
        return success

    @section_tool(mcp, "browser-management")
    async def get_instance_state(instance_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed state of a browser instance."""
        state = await browser_manager.get_page_state(instance_id)
        if state:
            return state.model_dump()
        return None

    @section_tool(mcp, "browser-management")
    async def navigate(
        instance_id: str,
        url: str,
        wait_until: str = "load",
        timeout: int = 30000,
        referrer: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Navigate to a URL.

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
            return {"url": final_url, "title": title, "success": True}
        except Exception:
            raise

    @section_tool(mcp, "browser-management")
    async def go_back(instance_id: str) -> bool:
        """Navigate back in history."""
        tab = await browser_manager.get_tab(instance_id)
        if not tab:
            raise Exception(f"Instance not found: {instance_id}")
        await tab.back()
        return True

    @section_tool(mcp, "browser-management")
    async def go_forward(instance_id: str) -> bool:
        """Navigate forward in history."""
        tab = await browser_manager.get_tab(instance_id)
        if not tab:
            raise Exception(f"Instance not found: {instance_id}")
        await tab.forward()
        return True

    @section_tool(mcp, "browser-management")
    async def reload_page(instance_id: str, ignore_cache: bool = False) -> bool:
        """Reload the current page."""
        tab = await browser_manager.get_tab(instance_id)
        if not tab:
            raise Exception(f"Instance not found: {instance_id}")
        await tab.reload()
        return True
