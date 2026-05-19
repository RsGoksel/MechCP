"""file-extraction MCP tools (auto-migrated from server.py)."""

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
    @section_tool(mcp, "file-extraction")
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

    @section_tool(mcp, "file-extraction")
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

    @section_tool(mcp, "file-extraction")
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

    @section_tool(mcp, "file-extraction")
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

    @section_tool(mcp, "file-extraction")
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

    @section_tool(mcp, "file-extraction")
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

    @section_tool(mcp, "file-extraction")
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

    @section_tool(mcp, "file-extraction")
    async def list_clone_files() -> List[Dict[str, Any]]:
        """
        List all element clone files saved to disk.

        Returns:
            List[Dict[str, Any]]: List of clone files with metadata and file information.
        """
        return file_based_element_cloner.list_clone_files()

    @section_tool(mcp, "file-extraction")
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
