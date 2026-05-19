"""element-interaction MCP tools (auto-migrated from server.py)."""

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
    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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

    @section_tool(mcp, "element-interaction")
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
