"""dynamic-hooks MCP tools (auto-migrated from server.py)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import nodriver as uc
from fastmcp import FastMCP
from nodriver import cdp

from debug_logger import debug_logger
from dynamic_hook_ai_interface import dynamic_hook_ai
from hook_learning_system import HookLearningSystem
from models import BrowserOptions, NavigationOptions, ScriptResult
from path_safety import safe_join, sanitize_filename
from persistent_storage import persistent_storage
from response_handler import response_handler
from safe_code import safe_compile

from ._helpers import (
    browser_manager,
    cdp_function_executor,
    dom_handler,
    element_cloner,
    network_interceptor,
    section_tool,
)


def register(mcp: FastMCP) -> None:
    @section_tool(mcp, "dynamic-hooks")
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

    @section_tool(mcp, "dynamic-hooks")
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

    @section_tool(mcp, "dynamic-hooks")
    async def list_dynamic_hooks(instance_id: Optional[str] = None) -> Dict[str, Any]:
        """
        List all dynamic hooks.
        
        Args:
            instance_id (Optional[str]): Optional filter by browser instance
            
        Returns:
            Dict[str, Any]: List of hooks with details and statistics
        """
        return await dynamic_hook_ai.list_dynamic_hooks(instance_id=instance_id)

    @section_tool(mcp, "dynamic-hooks")
    async def get_dynamic_hook_details(hook_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a specific dynamic hook.
        
        Args:
            hook_id (str): Hook identifier
            
        Returns:
            Dict[str, Any]: Detailed hook information including function code
        """
        return await dynamic_hook_ai.get_hook_details(hook_id=hook_id)

    @section_tool(mcp, "dynamic-hooks")
    async def remove_dynamic_hook(hook_id: str) -> Dict[str, Any]:
        """
        Remove a dynamic hook.
        
        Args:
            hook_id (str): Hook identifier to remove
            
        Returns:
            Dict[str, Any]: Removal status
        """
        return await dynamic_hook_ai.remove_dynamic_hook(hook_id=hook_id)
