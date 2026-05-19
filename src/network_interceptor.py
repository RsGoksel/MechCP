"""Network interception and traffic monitoring using CDP."""

import asyncio
import base64
import os
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Deque, Dict, FrozenSet, List, Optional

import nodriver as uc
from nodriver import Tab

from debug_logger import debug_logger
from models import NetworkRequest, NetworkResponse


_DEFAULT_PER_INSTANCE_CAP = int(os.environ.get("MECHCP_NETWORK_MAX_REQUESTS", "5000"))

# Resource types that are almost never useful to the agent and dominate the
# capture buffer on modern SPAs. Skipping them by default reduces Pydantic
# allocation churn ~70% on a typical news/SaaS page. Operators can capture
# everything by setting MECHCP_CAPTURE_ALL=1.
_DEFAULT_SKIP_RESOURCE_TYPES: FrozenSet[str] = frozenset(
    {"Image", "Font", "Media", "Stylesheet"}
)
_CAPTURE_ALL = os.environ.get("MECHCP_CAPTURE_ALL", "").strip() in {"1", "true", "yes"}


class NetworkInterceptor:
    """Intercept and store network traffic with bounded per-instance buffers.

    Each browser instance keeps a FIFO deque of request IDs. Once the cap is
    reached, the oldest entry is evicted from both the deque and the
    request/response stores so long-running sessions cannot exhaust memory.
    """

    def __init__(self, max_requests_per_instance: int = _DEFAULT_PER_INSTANCE_CAP) -> None:
        self._requests: Dict[str, NetworkRequest] = {}
        self._responses: Dict[str, NetworkResponse] = {}
        self._instance_requests: Dict[str, Deque[str]] = {}
        self._lock = asyncio.Lock()
        self._max_requests_per_instance = max(100, int(max_requests_per_instance))
        self._in_flight: Dict[str, int] = defaultdict(int)
        self._last_change: Dict[str, float] = defaultdict(time.monotonic)

    def _inc_in_flight(self, instance_id: str) -> None:
        self._in_flight[instance_id] += 1
        self._last_change[instance_id] = time.monotonic()

    def _dec_in_flight(self, instance_id: str) -> None:
        if self._in_flight[instance_id] > 0:
            self._in_flight[instance_id] -= 1
        self._last_change[instance_id] = time.monotonic()

    def in_flight_count(self, instance_id: str) -> int:
        return self._in_flight[instance_id]

    async def wait_for_idle(
        self,
        instance_id: str,
        idle_ms: int = 500,
        timeout_ms: int = 10000,
    ) -> bool:
        """Block until ``in_flight_count == 0`` has held for ``idle_ms`` ms.

        Returns True when settled, False on timeout. ``idle_ms`` defines the
        debounce window so a single momentary zero does not declare success.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        idle_s = idle_ms / 1000.0
        poll = max(0.025, idle_s / 5)
        while time.monotonic() < deadline:
            if self._in_flight[instance_id] == 0:
                if time.monotonic() - self._last_change[instance_id] >= idle_s:
                    return True
            await asyncio.sleep(poll)
        return False

    def _instance_buffer(self, instance_id: str) -> Deque[str]:
        """Return (and lazily create) the bounded request-id deque."""
        buf = self._instance_requests.get(instance_id)
        if buf is None:
            buf = deque(maxlen=self._max_requests_per_instance)
            self._instance_requests[instance_id] = buf
        return buf

    def _record_request(self, instance_id: str, request_id: str, request: NetworkRequest) -> None:
        """Insert a request and evict the oldest if the cap is reached."""
        buf = self._instance_buffer(instance_id)
        if buf.maxlen and len(buf) == buf.maxlen:
            evicted = buf[0]
            self._requests.pop(evicted, None)
            self._responses.pop(evicted, None)
        buf.append(request_id)
        self._requests[request_id] = request

    async def setup_interception(self, tab: Tab, instance_id: str, block_resources: List[str] = None):
        """
        Set up network interception for a tab.

        tab: Tab - The browser tab to intercept.
        instance_id: str - The browser instance identifier.
        block_resources: List[str] - List of resource types or URL patterns to block.
        """
        try:
            await tab.send(uc.cdp.network.enable())
            
            if block_resources:
                _NOISY_STEALTH = {"image", "font", "stylesheet"}
                noisy = [r for r in block_resources if str(r).lower() in _NOISY_STEALTH]
                if noisy:
                    debug_logger.log_warning(
                        "network_interceptor",
                        "setup_interception",
                        f"blocking {noisy} is a strong bot fingerprint; prefer URL patterns",
                    )

                # Convert resource types to URL patterns for blocking
                url_patterns = []
                for resource_type in block_resources:
                    # Map resource types to URL patterns that typically identify these resources
                    resource_patterns = {
                        'image': ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.webp', '*.svg', '*.bmp', '*.ico'],
                        'stylesheet': ['*.css'],
                        'font': ['*.woff', '*.woff2', '*.ttf', '*.otf', '*.eot'],
                        'script': ['*.js', '*.mjs'],
                        'media': ['*.mp4', '*.mp3', '*.wav', '*.avi', '*.webm']
                    }
                    
                    if resource_type.lower() in resource_patterns:
                        url_patterns.extend(resource_patterns[resource_type.lower()])
                        debug_logger.log_info(
                            "network_interceptor",
                            "setup_interception",
                            f"Added URL patterns for {resource_type}",
                        )
                    else:
                        # Assume it's already a URL pattern
                        url_patterns.append(resource_type)
                        debug_logger.log_info(
                            "network_interceptor",
                            "setup_interception",
                            f"Added custom URL pattern: {resource_type}",
                        )

                # Use network.set_blocked_ur_ls to block the URL patterns
                if url_patterns:
                    await tab.send(uc.cdp.network.set_blocked_ur_ls(urls=url_patterns))
                    debug_logger.log_info(
                        "network_interceptor",
                        "setup_interception",
                        f"Blocked {len(url_patterns)} URL patterns",
                    )

            tab.add_handler(
                uc.cdp.network.RequestWillBeSent,
                lambda event: asyncio.create_task(self._on_request(event, instance_id)),
            )
            tab.add_handler(
                uc.cdp.network.ResponseReceived,
                lambda event: asyncio.create_task(self._on_response(event, instance_id)),
            )

            # Terminal events that drive the in-flight counter for the
            # wait_for_idle helper. Decrementing on these (not on
            # ResponseReceived) avoids double-counting since ResponseReceived
            # fires when headers arrive, before the body completes.
            def _on_loading_finished(event):
                try:
                    self._dec_in_flight(instance_id)
                except Exception:
                    pass

            def _on_loading_failed(event):
                try:
                    self._dec_in_flight(instance_id)
                except Exception:
                    pass

            tab.add_handler(uc.cdp.network.LoadingFinished, _on_loading_finished)
            tab.add_handler(uc.cdp.network.LoadingFailed, _on_loading_failed)

            async with self._lock:
                self._instance_buffer(instance_id)
        except Exception as e:
            debug_logger.log_error("network_interceptor", "setup_interception", e)
            raise Exception(f"Failed to setup network interception: {str(e)}") from e

    async def _on_request(self, event, instance_id: str):
        """
        Handle request event.

        event: Any - The event object containing request data.
        instance_id: str - The browser instance identifier.
        """
        try:
            request_id = event.request_id
            request = event.request

            # Track in-flight for wait_for_idle. We increment even on filtered
            # captures so the counter reflects real network activity, not just
            # what we store.
            self._inc_in_flight(instance_id)

            # Default-filter noisy resource types unless the operator explicitly
            # opts in to capture everything.
            if not _CAPTURE_ALL:
                resource_type = getattr(event, "type", None)
                if resource_type is not None and str(resource_type) in _DEFAULT_SKIP_RESOURCE_TYPES:
                    return

            cookies = {}
            if hasattr(request, "headers") and "Cookie" in request.headers:
                cookie_str = request.headers["Cookie"]
                for cookie in cookie_str.split("; "):
                    if "=" in cookie:
                        key, value = cookie.split("=", 1)
                        cookies[key] = value
            network_request = NetworkRequest(
                request_id=request_id,
                instance_id=instance_id,
                url=request.url,
                method=request.method,
                headers=dict(request.headers) if hasattr(request, "headers") else {},
                cookies=cookies,
                post_data=request.post_data if hasattr(request, "post_data") else None,
                resource_type=event.type if hasattr(event, "type") else None,
            )
            async with self._lock:
                self._record_request(instance_id, request_id, network_request)
        except Exception as exc:
            debug_logger.log_error("network_interceptor", "_on_request", exc)

    async def _on_response(self, event, instance_id: str):
        """
        Handle response event.

        event: Any - The event object containing response data.
        instance_id: str - The browser instance identifier.
        """
        try:
            request_id = event.request_id
            response = event.response
            network_response = NetworkResponse(
                request_id=request_id,
                status=response.status,
                headers=dict(response.headers) if hasattr(response, "headers") else {},
                content_type=response.mime_type if hasattr(response, "mime_type") else None,
            )
            async with self._lock:
                self._responses[request_id] = network_response
        except Exception as exc:
            debug_logger.log_error("network_interceptor", "_on_response", exc)


    async def list_requests(self, instance_id: str, filter_type: Optional[str] = None) -> List[NetworkRequest]:
        """
        List all requests for an instance.

        instance_id: str - The browser instance identifier.
        filter_type: Optional[str] - Filter requests by resource type.
        Returns: List[NetworkRequest] - List of network requests.
        """
        async with self._lock:
            request_ids = self._instance_requests.get(instance_id, [])
            requests = []
            for req_id in request_ids:
                if req_id in self._requests:
                    request = self._requests[req_id]
                    if filter_type:
                        if request.resource_type and filter_type.lower() in request.resource_type.lower():
                            requests.append(request)
                    else:
                        requests.append(request)
            return requests

    async def get_request(self, request_id: str) -> Optional[NetworkRequest]:
        """
        Get specific request by ID.

        request_id: str - The request identifier.
        Returns: Optional[NetworkRequest] - The network request object or None.
        """
        async with self._lock:
            return self._requests.get(request_id)

    async def get_response(self, request_id: str) -> Optional[NetworkResponse]:
        """
        Get response for a request.

        request_id: str - The request identifier.
        Returns: Optional[NetworkResponse] - The network response object or None.
        """
        async with self._lock:
            return self._responses.get(request_id)

    async def get_response_body(self, tab: Tab, request_id: str) -> Optional[bytes]:
        """
        Get response body content.

        tab: Tab - The browser tab.
        request_id: str - The request identifier.
        Returns: Optional[bytes] - The response body as bytes, or None.
        """
        try:
            # Convert string to RequestId object
            request_id_obj = uc.cdp.network.RequestId(request_id)
            result = await tab.send(uc.cdp.network.get_response_body(request_id=request_id_obj))
            if result:
                body, base64_encoded = result  # Result is a tuple (body, base64Encoded)
                if base64_encoded:
                    return base64.b64decode(body)
                else:
                    return body.encode("utf-8")
        except Exception:
            pass
        return None

    async def modify_headers(self, tab: Tab, headers: Dict[str, str]):
        """
        Modify request headers for future requests.

        tab: Tab - The browser tab.
        headers: Dict[str, str] - Headers to set.
        Returns: bool - True if successful.
        """
        try:
            # Convert dict to Headers object
            headers_obj = uc.cdp.network.Headers(headers)
            await tab.send(uc.cdp.network.set_extra_http_headers(headers=headers_obj))
            return True
        except Exception as e:
            raise Exception(f"Failed to modify headers: {str(e)}")

    async def set_user_agent(self, tab: Tab, user_agent: str):
        """Set custom user agent and matching Sec-CH-UA client hints.

        Pairs the override with parsed userAgentMetadata so the spoofed UA
        does not collide with real client-hint values, which is otherwise a
        high-signal bot fingerprint.
        """
        from stealth_scripts import parse_user_agent_metadata

        try:
            meta = parse_user_agent_metadata(user_agent)
            if meta is not None:
                try:
                    metadata = uc.cdp.emulation.UserAgentMetadata(
                        platform=meta["platform"],
                        platform_version=meta["platform_version"],
                        architecture=meta["architecture"],
                        bitness=meta["bitness"],
                        model=meta["model"],
                        mobile=meta["mobile"],
                        brands=[
                            uc.cdp.emulation.UserAgentBrandVersion(
                                brand=b["brand"], version=b["version"]
                            )
                            for b in meta["brands"]
                        ],
                    )
                    await tab.send(
                        uc.cdp.emulation.set_user_agent_override(
                            user_agent=user_agent, user_agent_metadata=metadata
                        )
                    )
                    return True
                except Exception as exc:
                    debug_logger.log_warning(
                        "network_interceptor",
                        "set_user_agent",
                        f"client-hints metadata build failed, falling back to UA-only: {exc}",
                    )
            await tab.send(uc.cdp.network.set_user_agent_override(user_agent=user_agent))
            return True
        except Exception as e:
            raise Exception(f"Failed to set user agent: {str(e)}") from e

    async def enable_cache(self, tab: Tab, enabled: bool = True):
        """
        Enable or disable cache.

        tab: Tab - The browser tab.
        enabled: bool - True to enable cache, False to disable.
        Returns: bool - True if successful.
        """
        try:
            await tab.send(uc.cdp.network.set_cache_disabled(cache_disabled=not enabled))
            return True
        except Exception as e:
            raise Exception(f"Failed to set cache state: {str(e)}")

    async def clear_browser_cache(self, tab: Tab):
        """
        Clear browser cache.

        tab: Tab - The browser tab.
        Returns: bool - True if successful.
        """
        try:
            await tab.send(uc.cdp.network.clear_browser_cache())
            return True
        except Exception as e:
            raise Exception(f"Failed to clear cache: {str(e)}")

    async def clear_cookies(self, tab: Tab, url: Optional[str] = None):
        """
        Clear cookies.

        tab: Tab - The browser tab.
        url: Optional[str] - The URL for which to clear cookies, or None to clear all.
        Returns: bool - True if successful.
        """
        try:
            if url:
                # For specific URL, get all cookies for that URL and delete them
                cookies = await tab.send(uc.cdp.network.get_cookies(urls=[url]))
                for cookie in cookies:
                    await tab.send(
                        uc.cdp.network.delete_cookies(
                            name=cookie.name,
                            url=url
                        )
                    )
            else:
                # Clear all browser cookies using the proper method
                await tab.send(uc.cdp.network.clear_browser_cookies())
            return True
        except Exception as e:
            raise Exception(f"Failed to clear cookies: {str(e)}")

    async def set_cookie(self, tab: Tab, cookie: Dict[str, Any]):
        """
        Set a cookie.

        tab: Tab - The browser tab.
        cookie: Dict[str, Any] - Cookie parameters.
        Returns: bool - True if successful.
        """
        try:
            await tab.send(uc.cdp.network.set_cookie(**cookie))
            return True
        except Exception as e:
            raise Exception(f"Failed to set cookie: {str(e)}")

    async def get_cookies(self, tab: Tab, urls: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Get cookies.

        tab: Tab - The browser tab.
        urls: Optional[List[str]] - List of URLs to get cookies for, or None for all.
        Returns: List[Dict[str, Any]] - List of cookies.
        """
        try:
            if urls:
                result = await tab.send(uc.cdp.network.get_cookies(urls=urls))
            else:
                result = await tab.send(uc.cdp.network.get_all_cookies())
            if isinstance(result, dict):
                return result.get("cookies", [])
            elif isinstance(result, list):
                return result
            else:
                return []
        except Exception as e:
            raise Exception(f"Failed to get cookies: {str(e)}")

    async def emulate_network_conditions(
        self,
        tab: Tab,
        offline: bool = False,
        latency: int = 0,
        download_throughput: int = -1,
        upload_throughput: int = -1,
    ):
        """
        Emulate network conditions.

        tab: Tab - The browser tab.
        offline: bool - Whether to emulate offline mode.
        latency: int - Additional latency (ms).
        download_throughput: int - Download speed (bytes/sec).
        upload_throughput: int - Upload speed (bytes/sec).
        Returns: bool - True if successful.
        """
        try:
            await tab.send(
                uc.cdp.network.emulate_network_conditions(
                    offline=offline,
                    latency=latency,
                    download_throughput=download_throughput,
                    upload_throughput=upload_throughput,
                )
            )
            return True
        except Exception as e:
            raise Exception(f"Failed to emulate network conditions: {str(e)}")

    async def clear_instance_data(self, instance_id: str):
        """
        Clear all network data for an instance.

        instance_id: str - The browser instance identifier.
        """
        async with self._lock:
            buf = self._instance_requests.pop(instance_id, None)
            if buf:
                for req_id in buf:
                    self._requests.pop(req_id, None)
                    self._responses.pop(req_id, None)