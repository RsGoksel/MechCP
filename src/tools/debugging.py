"""Debugging MCP tools: console logs, debug view, log export, hot reload."""

from __future__ import annotations

import asyncio
import importlib
import sys
from typing import Any, Dict, Optional

from fastmcp import FastMCP

from browser_manager import BrowserManager
from debug_logger import debug_logger
from dom_handler import DOMHandler
from network_interceptor import NetworkInterceptor
from platform_utils import get_platform_info, validate_browser_environment

from ._helpers import browser_manager, section_tool


def register(mcp: FastMCP) -> None:
    @section_tool(mcp, "debugging")
    async def get_console_logs(
        instance_id: str,
        since_index: int = 0,
        level_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return browser console messages captured since spawn.

        Args:
            instance_id (str): Browser instance ID.
            since_index (int): Return entries at index >= this value. The agent
                can poll incrementally by passing the previous ``next_index``.
            level_filter (Optional[str]): If set, only return entries whose level
                matches (e.g. 'error', 'warning').

        Returns:
            Dict[str, Any]: ``{instance_id, total, returned, next_index, entries}``.
        """
        async with browser_manager._lock:
            inst = browser_manager._instances.get(instance_id)
            if inst is None:
                return {"error": f"Instance not found: {instance_id}"}
            logs = list(inst.get("console_logs", []))

        if level_filter:
            logs = [e for e in logs if str(e.get("level", "")).lower() == level_filter.lower()]
        slice_start = max(0, int(since_index))
        entries = logs[slice_start:]
        return {
            "instance_id": instance_id,
            "total": len(logs),
            "returned": len(entries),
            "next_index": len(logs),
            "entries": entries[-200:],
        }

    @section_tool(mcp, "debugging")
    async def get_debug_view(
        max_errors: int = 50,
        max_warnings: int = 50,
        max_info: int = 50,
        include_all: bool = False,
    ) -> Dict[str, Any]:
        """Get comprehensive debug view with all logged errors and statistics."""
        return debug_logger.get_debug_view_paginated(
            max_errors=max_errors if not include_all else None,
            max_warnings=max_warnings if not include_all else None,
            max_info=max_info if not include_all else None,
        )

    @section_tool(mcp, "debugging")
    async def clear_debug_view() -> bool:
        """Clear all debug logs and statistics with timeout protection."""
        try:
            await asyncio.wait_for(
                asyncio.to_thread(debug_logger.clear_debug_view_safe),
                timeout=10.0,
            )
            return True
        except asyncio.TimeoutError:
            return False

    @section_tool(mcp, "debugging")
    async def export_debug_logs(
        filename: str = "debug_log.json",
        max_errors: int = 100,
        max_warnings: int = 100,
        max_info: int = 100,
        include_all: bool = False,
        format: str = "auto",
    ) -> str:
        """Export debug logs to a JSON file inside the MECHCP_OUTPUT_DIR sandbox.

        Path separators are stripped and the file must end with ``.json``.
        Pickle exports were removed because pickle deserialization is a
        code-execution sink.
        """
        try:
            filepath = await asyncio.wait_for(
                asyncio.to_thread(
                    debug_logger.export_to_file_paginated,
                    filename,
                    max_errors if not include_all else None,
                    max_warnings if not include_all else None,
                    max_info if not include_all else None,
                    format,
                ),
                timeout=30.0,
            )
            return filepath
        except ValueError as exc:
            return f"unsafe filename rejected: {exc}"
        except asyncio.TimeoutError:
            return "Export timeout - file too large. Try with smaller limits."

    @section_tool(mcp, "debugging")
    async def get_debug_lock_status() -> Dict[str, Any]:
        """Get current debug logger lock status for diagnosing hanging exports."""
        try:
            return debug_logger.get_lock_status()
        except Exception as e:
            return {"error": str(e)}

    @section_tool(mcp, "debugging")
    async def hot_reload() -> str:
        """Hot reload core modules without restarting the server."""
        try:
            modules_to_reload = [
                "browser_manager",
                "network_interceptor",
                "dom_handler",
                "debug_logger",
                "models",
            ]
            reloaded = []
            for name in modules_to_reload:
                if name in sys.modules:
                    importlib.reload(sys.modules[name])
                    reloaded.append(name)
            return f"Hot reload completed. Reloaded modules: {', '.join(reloaded)}"
        except Exception as e:
            return f"Hot reload failed: {str(e)}"

    @section_tool(mcp, "debugging")
    async def reload_status() -> str:
        """Check the load status of core modules."""
        try:
            modules_to_check = [
                "browser_manager",
                "network_interceptor",
                "dom_handler",
                "debug_logger",
                "models",
                "persistent_storage",
            ]
            lines = []
            for name in modules_to_check:
                if name in sys.modules:
                    module = sys.modules[name]
                    lines.append(f"loaded {name}: {getattr(module, '__file__', 'built-in')}")
                else:
                    lines.append(f"not loaded: {name}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error checking module status: {str(e)}"

    @section_tool(mcp, "debugging")
    async def validate_browser_environment_tool() -> Dict[str, Any]:
        """Validate browser environment and diagnose potential issues."""
        try:
            return validate_browser_environment()
        except Exception as e:
            return {
                "error": str(e),
                "platform_info": get_platform_info(),
                "is_ready": False,
                "issues": [f"Validation failed: {str(e)}"],
                "warnings": [],
            }
