"""Network-debugging MCP tools: request/response capture, header overrides."""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional, Union

from fastmcp import FastMCP

from response_handler import response_handler

from ._helpers import browser_manager, network_interceptor, section_tool


def register(mcp: FastMCP) -> None:
    @section_tool(mcp, "network-debugging")
    async def list_network_requests(
        instance_id: str,
        filter_type: Optional[str] = None,
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """List captured network requests.

        Args:
            instance_id (str): Browser instance ID.
            filter_type (Optional[str]): Filter by resource type
                (e.g. 'image', 'script', 'xhr').

        Returns:
            Union[List[Dict[str, Any]], Dict[str, Any]]: List of network
            requests, or file metadata if the response is too large.
        """
        requests = await network_interceptor.list_requests(instance_id, filter_type)
        formatted = [
            {
                "request_id": req.request_id,
                "url": req.url,
                "method": req.method,
                "resource_type": req.resource_type,
                "timestamp": req.timestamp.isoformat(),
            }
            for req in requests
        ]
        return response_handler.handle_response(formatted, "network_requests")

    @section_tool(mcp, "network-debugging")
    async def get_request_details(
        request_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get detailed information about a network request."""
        request = await network_interceptor.get_request(request_id)
        if request:
            return request.model_dump()
        return None

    @section_tool(mcp, "network-debugging")
    async def get_response_details(
        request_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get response details (status, headers, mime type) for a network request."""
        response = await network_interceptor.get_response(request_id)
        if response:
            return response.model_dump()
        return None

    @section_tool(mcp, "network-debugging")
    async def get_response_content(
        instance_id: str,
        request_id: str,
    ) -> Optional[str]:
        """Get response body content as text, or base64 for binary payloads."""
        tab = await browser_manager.get_tab(instance_id)
        if not tab:
            raise Exception(f"Instance not found: {instance_id}")
        body = await network_interceptor.get_response_body(tab, request_id)
        if body:
            try:
                return body.decode("utf-8")
            except UnicodeDecodeError:
                return base64.b64encode(body).decode("utf-8")
        return None

    @section_tool(mcp, "network-debugging")
    async def modify_headers(
        instance_id: str,
        headers: Dict[str, str],
    ) -> bool:
        """Modify request headers for future requests."""
        tab = await browser_manager.get_tab(instance_id)
        if not tab:
            raise Exception(f"Instance not found: {instance_id}")
        return await network_interceptor.modify_headers(tab, headers)
