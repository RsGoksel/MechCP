"""DOM manipulation and element interaction utilities."""

import asyncio
import time
from typing import List, Optional, Dict, Any

from nodriver import Tab, Element
from models import ElementInfo, ElementAction
from debug_logger import debug_logger



class DOMHandler:
    """Handles DOM queries and element interactions."""

    @staticmethod
    async def query_elements(
        tab: Tab,
        selector: str,
        text_filter: Optional[str] = None,
        visible_only: bool = True,
        limit: Optional[Any] = None
    ) -> List[ElementInfo]:
        """
        Query elements with advanced filtering.

        Args:
            tab (Tab): The browser tab object.
            selector (str): CSS or XPath selector for elements.
            text_filter (Optional[str]): Filter elements by text content.
            visible_only (bool): Only include visible elements.
            limit (Optional[Any]): Limit the number of results.

        Returns:
            List[ElementInfo]: List of element information objects.
        """
        processed_limit = None
        if limit is not None:
            try:
                if isinstance(limit, int):
                    processed_limit = limit
                elif isinstance(limit, str) and limit.isdigit():
                    processed_limit = int(limit)
                elif isinstance(limit, str) and limit.strip() == '':
                    processed_limit = None
                else:
                    debug_logger.log_warning('DOMHandler', 'query_elements',
                                            f'Invalid limit parameter: {limit} (type: {type(limit)})')
                    processed_limit = None
            except (ValueError, TypeError) as e:
                debug_logger.log_error('DOMHandler', 'query_elements', e,
                                      {'limit_value': limit, 'limit_type': type(limit)})
                processed_limit = None

        debug_logger.log_info('DOMHandler', 'query_elements',
                             f'Starting query with selector: {selector}',
                             {'text_filter': text_filter, 'visible_only': visible_only,
                              'limit': limit, 'processed_limit': processed_limit})
        try:
            if selector.startswith('//'):
                elements = await tab.select_all(f'xpath={selector}')
                debug_logger.log_info('DOMHandler', 'query_elements',
                                     f'XPath query returned {len(elements)} elements')
            else:
                elements = await tab.select_all(selector)
                debug_logger.log_info('DOMHandler', 'query_elements',
                                     f'CSS query returned {len(elements)} elements')

            results = []
            for idx, elem in enumerate(elements):
                try:
                    debug_logger.log_info('DOMHandler', 'query_elements',
                                         f'Processing element {idx+1}/{len(elements)}')

                    if hasattr(elem, 'update'):
                        await elem.update()
                        debug_logger.log_info('DOMHandler', 'query_elements',
                                             f'Element {idx+1} updated')

                    tag_name = elem.tag_name if hasattr(elem, 'tag_name') else 'unknown'
                    text_content = elem.text_all if hasattr(elem, 'text_all') else ''
                    attrs = elem.attrs if hasattr(elem, 'attrs') else {}

                    debug_logger.log_info('DOMHandler', 'query_elements',
                                         f'Element {idx+1}: tag={tag_name}, text_len={len(text_content)}, attrs={len(attrs)}')

                    if text_filter and text_filter.lower() not in text_content.lower():
                        continue

                    is_visible = True
                    if visible_only:
                        try:
                            is_visible = await elem.apply(
                                """(elem) => {
                                    var style = window.getComputedStyle(elem);
                                    return style.display !== 'none' && 
                                           style.visibility !== 'hidden' && 
                                           style.opacity !== '0';
                                }"""
                            )
                            if not is_visible:
                                continue
                        except Exception:
                            pass

                    bbox = None
                    try:
                        position = await elem.get_position()
                        if position:
                            bbox = {
                                'x': position.x,
                                'y': position.y,
                                'width': position.width,
                                'height': position.height
                            }
                            debug_logger.log_info('DOMHandler', 'query_elements',
                                                 f'Element {idx+1} position: {bbox}')
                    except Exception as pos_error:
                        debug_logger.log_warning('DOMHandler', 'query_elements',
                                                f'Could not get position for element {idx+1}: {pos_error}')

                    is_clickable = False

                    children_count = 0
                    try:
                        if hasattr(elem, 'children'):
                            children = elem.children
                            children_count = len(children) if children else 0
                    except Exception:
                        pass

                    element_info = ElementInfo(
                        selector=selector,
                        tag_name=tag_name,
                        text=text_content[:500] if text_content else None,
                        attributes=attrs or {},
                        is_visible=is_visible,
                        is_clickable=is_clickable,
                        bounding_box=bbox,
                        children_count=children_count
                    )

                    results.append(element_info)

                    if processed_limit and len(results) >= processed_limit:
                        debug_logger.log_info('DOMHandler', 'query_elements',
                                             f'Reached limit of {processed_limit} results')
                        break

                except Exception as elem_error:
                    debug_logger.log_error('DOMHandler', 'query_elements',
                                          elem_error,
                                          {'element_index': idx, 'selector': selector})
                    continue

            debug_logger.log_info('DOMHandler', 'query_elements',
                                 f'Returning {len(results)} results')
            return results

        except Exception as e:
            debug_logger.log_error('DOMHandler', 'query_elements', e,
                                  {'selector': selector, 'tab': str(tab)})
            return []

    @staticmethod
    async def list_frames(tab: Optional[Tab]) -> List[Dict[str, Any]]:
        """Enumerate iframes in the page with stable frame IDs.

        Returns ``[{frame_id, url, name, parent_frame_id}]`` for each iframe
        the page has loaded. ``frame_id`` is the CDP frame ID. Currently the
        per-frame interaction routing is a stub (see ``_resolve_frame_tab``),
        but the enumeration tool ships now so agents can at least discover
        iframe URLs and make routing decisions in their prompts.

        Returns ``[]`` when the tab is missing or the page has no iframes.
        """
        if tab is None:
            return []
        try:
            tree = await tab.send(uc.cdp.page.get_frame_tree())
        except Exception:
            return []

        out: List[Dict[str, Any]] = []

        def walk(node, parent_id):
            try:
                frame = node.frame
                out.append({
                    "frame_id": str(frame.id_),
                    "url": getattr(frame, "url", "") or "",
                    "name": getattr(frame, "name", None),
                    "parent_frame_id": parent_id,
                })
                for child in (getattr(node, "child_frames", None) or []):
                    walk(child, str(frame.id_))
            except Exception:
                pass

        try:
            walk(tree, parent_id=None)
        except Exception:
            return []
        # Drop the root frame (only iframes are interesting to the agent).
        return [f for f in out if f["parent_frame_id"] is not None]

    @staticmethod
    async def _resolve_frame_tab(tab, frame_id: Optional[str]):
        """Return the target tab for the requested frame, or None if unsupported.

        - ``frame_id is None`` returns the input tab unchanged (top-level
          targeting, the existing behavior).
        - ``frame_id`` set but ``tab is None`` returns None.
        - ``frame_id`` set on a live tab also returns None today: nodriver
          does not expose per-frame Tab objects, so we cannot route a click
          into an iframe without a richer abstraction. Returning None here
          (rather than silently using the main tab) lets the MCP wrapper
          surface an explicit "not yet supported" error to the agent.

        Future improvement: use ``Target.attachToTarget`` for OOPIFs.
        """
        if frame_id is None:
            return tab
        return None

    @staticmethod
    async def query_shadow(
        tab: Optional[Tab],
        selector: str,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """Find elements that match ``selector`` anywhere in the document, piercing open shadow roots.

        Returns a list of element snapshots (``tag, id, classes, text, attrs,
        box, shadow_path``). ``shadow_path`` is the list of host-tag names that
        led into the shadow root containing the element, so the agent can tell
        whether the element is inside ``<youtube-search>`` versus
        ``<github-app>``.

        Returns ``[]`` when ``tab`` is None or the underlying evaluate fails,
        so the caller can fall back to ``query_elements`` without try/except.
        """
        import json as _json
        from pathlib import Path as _Path

        if tab is None:
            return []

        js_path = _Path(__file__).parent / "js" / "query_deep.js"
        if not js_path.exists():
            return []

        template = js_path.read_text(encoding="utf-8")
        js = template.replace("$SELECTOR", _json.dumps(selector))
        js = js.replace("$LIMIT", str(max(1, int(max_results))))

        try:
            result = await tab.evaluate(js)
        except Exception:
            return []
        if not isinstance(result, list):
            return []
        return result

    @staticmethod
    async def click_element(
        tab: Tab,
        selector: str,
        text_match: Optional[str] = None,
        timeout: int = 10000,
    ) -> Dict[str, Any]:
        """Click an element and return a post-state verification report.

        Args:
            tab (Tab): The browser tab object.
            selector (str): CSS selector for the element.
            text_match (Optional[str]): Match element by text content instead.
            timeout (int): Timeout in milliseconds for element resolution.

        Returns:
            Dict[str, Any]: ``{success, navigated, dom_mutated, url_before,
            url_after, outer_html_hash_before, outer_html_hash_after, error}``.
            ``navigated``/``dom_mutated`` are how the caller verifies the click
            actually had an effect, vs. silently hitting a covering overlay.
        """
        import hashlib as _hashlib

        def _hash_dom(html: str) -> str:
            return _hashlib.blake2b(html.encode("utf-8", "ignore"), digest_size=8).hexdigest()

        try:
            url_before = getattr(tab, "url", "") or ""
            try:
                outer_before = await tab.evaluate(
                    "document.documentElement.outerHTML.slice(0, 200000)"
                )
                outer_before = outer_before if isinstance(outer_before, str) else ""
            except Exception:
                outer_before = ""
            hash_before = _hash_dom(outer_before)

            element = None
            if text_match:
                element = await tab.find(text_match, best_match=True)
            else:
                element = await tab.select(selector, timeout=timeout / 1000)

            if not element:
                return {
                    "success": False,
                    "navigated": False,
                    "dom_mutated": False,
                    "error": f"Element not found: {selector}",
                }

            await element.scroll_into_view()
            await asyncio.sleep(0.2)

            # Send a short jittered mouse trajectory toward the target before
            # the actual click. Pure CDP center-point clicks with no pointer
            # history are a high-signal "no human input" pattern.
            try:
                from stealth_scripts import bezier_path
                from nodriver import cdp as _cdp
                import json as _json

                target_query = selector if selector else None
                if target_query:
                    box = await tab.evaluate(
                        f"(() => {{ const el = document.querySelector({_json.dumps(target_query)});"
                        " if (!el) return null;"
                        " const r = el.getBoundingClientRect();"
                        " return {x: r.x + r.width/2, y: r.y + r.height/2}; }})()"
                    )
                    if isinstance(box, dict) and "x" in box and "y" in box:
                        start = (
                            max(0.0, float(box["x"]) - 200.0),
                            max(0.0, float(box["y"]) - 80.0),
                        )
                        for x, y, dwell in bezier_path(start, (float(box["x"]), float(box["y"]))):
                            await tab.send(
                                _cdp.input_.dispatch_mouse_event(
                                    type_="mouseMoved", x=x, y=y, button="none",
                                )
                            )
                            await asyncio.sleep(dwell)
            except Exception as exc:
                debug_logger.log_warning(
                    "dom_handler",
                    "click_element",
                    f"mouse trajectory failed (continuing with direct click): {exc}",
                )

            try:
                await element.click()
            except Exception:
                await element.mouse_click()
            await asyncio.sleep(0.4)

            try:
                url_after = await tab.evaluate("window.location.href")
            except Exception:
                url_after = None
            try:
                outer_after = await tab.evaluate(
                    "document.documentElement.outerHTML.slice(0, 200000)"
                )
                outer_after = outer_after if isinstance(outer_after, str) else ""
            except Exception:
                outer_after = ""
            hash_after = _hash_dom(outer_after)

            return {
                "success": True,
                "navigated": isinstance(url_after, str) and url_after != url_before,
                "dom_mutated": hash_after != hash_before,
                "url_before": url_before,
                "url_after": url_after if isinstance(url_after, str) else None,
                "outer_html_hash_before": hash_before,
                "outer_html_hash_after": hash_after,
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "navigated": False,
                "dom_mutated": False,
                "error": str(e),
            }

    @staticmethod
    async def type_text(
        tab: Tab,
        selector: str,
        text: str,
        clear_first: bool = True,
        delay_ms: int = 50,
        parse_newlines: bool = False,
        shift_enter: bool = False,
        fast: bool = False,
    ) -> bool:
        """Type text into an element.

        Args:
            tab (Tab): The browser tab object.
            selector (str): CSS selector for the input element.
            text (str): Text to type.
            clear_first (bool): Clear input before typing.
            delay_ms (int): Mean delay between keystrokes (ms). Per-key delay is
                jittered with Gaussian noise around this mean to avoid the
                perfectly-regular interval pattern that bot detectors flag.
            parse_newlines (bool): If True, parse \n as Enter key presses.
            shift_enter (bool): If True, use Shift+Enter instead of Enter (for chat apps).
            fast (bool): If True (or ``delay_ms == 0``), insert the text in a
                single CDP roundtrip via ``Input.insertText`` instead of
                per-character ``send_keys``. ~100x faster for long inputs but
                bypasses keystroke timing fingerprints, so prefer ``False`` for
                stealth-sensitive interactions.

        Returns:
            bool: True if typing succeeded, False otherwise.
        """
        import random

        try:
            element = await tab.select(selector)
            if not element:
                raise Exception(f"Element not found: {selector}")

            await element.focus()
            await asyncio.sleep(0.1)

            if clear_first:
                try:
                    await element.apply("(elem) => { elem.value = ''; }")
                except Exception:
                    await element.send_keys('\ue009' + 'a')
                    await element.send_keys('\ue017')
                await asyncio.sleep(0.1)

            # Fast path: a single Input.insertText covers the whole string
            # in one CDP roundtrip.
            if (fast or delay_ms <= 0) and not parse_newlines:
                from nodriver import cdp as _cdp
                try:
                    await tab.send(_cdp.input_.insert_text(text=text))
                    return True
                except Exception:
                    # Fall through to the per-key path if insert_text is rejected.
                    pass

            def _jittered_delay() -> float:
                """Gaussian-jittered delay so inter-key intervals are not constant."""
                mean_s = max(delay_ms, 1) / 1000.0
                std_s = mean_s / 4.0
                return max(0.005, random.gauss(mean_s, std_s))

            if parse_newlines:
                from nodriver import cdp
                lines = text.split('\n')
                for i, line in enumerate(lines):
                    for char in line:
                        await element.send_keys(char)
                        await asyncio.sleep(_jittered_delay())
                    
                    if i < len(lines) - 1:
                        if shift_enter:
                            await element.apply('''(elem) => {
                                const start = elem.selectionStart;
                                const end = elem.selectionEnd;
                                const value = elem.value;
                                elem.value = value.substring(0, start) + '\\n' + value.substring(end);
                                elem.selectionStart = elem.selectionEnd = start + 1;
                                
                                elem.dispatchEvent(new KeyboardEvent('keydown', {
                                    key: 'Enter',
                                    code: 'Enter',
                                    shiftKey: true,
                                    bubbles: true
                                }));
                                elem.dispatchEvent(new Event('input', { bubbles: true }));
                            }''')
                        else:
                            await element.apply('''(elem) => {
                                const start = elem.selectionStart;
                                const end = elem.selectionEnd;
                                const value = elem.value;
                                elem.value = value.substring(0, start) + '\\n' + value.substring(end);
                                elem.selectionStart = elem.selectionEnd = start + 1;
                                
                                elem.dispatchEvent(new KeyboardEvent('keydown', {
                                    key: 'Enter',
                                    code: 'Enter',
                                    bubbles: true
                                }));
                                elem.dispatchEvent(new Event('input', { bubbles: true }));
                            }''')
                        await asyncio.sleep(delay_ms / 1000)
            else:
                for char in text:
                    await element.send_keys(char)
                    await asyncio.sleep(delay_ms / 1000)

            return True

        except Exception as e:
            raise Exception(f"Failed to type text: {str(e)}")

    @staticmethod
    async def paste_text(
        tab: Tab,
        selector: str,
        text: str,
        clear_first: bool = True
    ) -> bool:
        """
        Paste text instantly using nodriver's insert_text method.
        This is much faster than typing character by character.

        Args:
            tab (Tab): The browser tab object.
            selector (str): CSS selector for the input element.
            text (str): Text to paste.
            clear_first (bool): Clear input before pasting.

        Returns:
            bool: True if pasting succeeded, False otherwise.
        """
        from nodriver import cdp
        
        try:
            element = await tab.select(selector)
            if not element:
                raise Exception(f"Element not found: {selector}")

            await element.focus()
            await asyncio.sleep(0.1)

            if clear_first:
                try:
                    await element.apply("(elem) => { elem.value = ''; }")
                except Exception:
                    await tab.send(cdp.input_.dispatch_key_event(
                        "rawKeyDown", 
                        modifiers=2,  # Ctrl
                        key="a",
                        code="KeyA",
                        windows_virtual_key_code=65
                    ))
                    await tab.send(cdp.input_.dispatch_key_event(
                        "keyUp", 
                        modifiers=2,  # Ctrl
                        key="a",
                        code="KeyA",
                        windows_virtual_key_code=65
                    ))
                    await tab.send(cdp.input_.dispatch_key_event(
                        "rawKeyDown",
                        key="Delete",
                        code="Delete",
                        windows_virtual_key_code=46
                    ))
                    await tab.send(cdp.input_.dispatch_key_event(
                        "keyUp",
                        key="Delete", 
                        code="Delete",
                        windows_virtual_key_code=46
                    ))
                await asyncio.sleep(0.1)

            await tab.send(cdp.input_.insert_text(text))

            return True

        except Exception as e:
            raise Exception(f"Failed to paste text: {str(e)}")

    @staticmethod
    async def select_option(
        tab: Tab,
        selector: str,
        value: Optional[str] = None,
        text: Optional[str] = None,
        index: Optional[int] = None
    ) -> bool:
        """
        Select option from dropdown using nodriver's native methods.

        Args:
            tab (Tab): The browser tab object.
            selector (str): CSS selector for the select element.
            value (Optional[str]): Option value to select.
            text (Optional[str]): Option text to select.
            index (Optional[int]): Option index to select.

        Returns:
            bool: True if option selected, False otherwise.
        """
        try:
            select_element = await tab.select(selector)
            if not select_element:
                raise Exception(f"Select element not found: {selector}")

            if text is not None:
                await select_element.send_keys(text)
                return True

            if value is not None:
                await tab.evaluate(f"""
                    const select = document.querySelector('{selector}');
                    if (select) {{
                        select.value = '{value}';
                        select.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                """)
                return True

            elif index is not None:
                await tab.evaluate(f"""
                    const select = document.querySelector('{selector}');
                    if (select && {index} >= 0 && {index} < select.options.length) {{
                        select.selectedIndex = {index};
                        select.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                """)
                return True

            raise Exception("No selection criteria provided (value, text, or index)")

        except Exception as e:
            raise Exception(f"Failed to select option: {str(e)}")

    @staticmethod
    async def get_element_state(
        tab: Tab,
        selector: str
    ) -> Dict[str, Any]:
        """
        Get complete state of an element.

        Args:
            tab (Tab): The browser tab object.
            selector (str): CSS selector for the element.

        Returns:
            Dict[str, Any]: Dictionary of element state properties.
        """
        try:
            element = await tab.select(selector)
            if not element:
                raise Exception(f"Element not found: {selector}")

            if hasattr(element, 'update'):
                await element.update()

            state = {
                'tag_name': element.tag_name if hasattr(element, 'tag_name') else 'unknown',
                'text': element.text if hasattr(element, 'text') else '',
                'text_all': element.text_all if hasattr(element, 'text_all') else '',
                'attributes': element.attrs if hasattr(element, 'attrs') else {},
                'is_visible': True,
                'is_clickable': False,
                'is_enabled': True,
                'value': element.attrs.get('value') if hasattr(element, 'attrs') else None,
                'href': element.attrs.get('href') if hasattr(element, 'attrs') else None,
                'src': element.attrs.get('src') if hasattr(element, 'attrs') else None,
                'class': element.attrs.get('class') if hasattr(element, 'attrs') else None,
                'id': element.attrs.get('id') if hasattr(element, 'attrs') else None,
                'position': await element.get_position() if hasattr(element, 'get_position') else None,
                'computed_style': {},
                'children_count': len(element.children) if hasattr(element, 'children') and element.children else 0,
                'parent_tag': None
            }

            return state

        except Exception as e:
            raise Exception(f"Failed to get element state: {str(e)}")

    @staticmethod
    async def wait_for_element(
        tab: Tab,
        selector: str,
        timeout: int = 30000,
        visible: bool = True,
        text_content: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Wait for ``selector`` to appear (and optionally become visible / contain text).

        Pushes a single MutationObserver into the page that resolves a promise
        when the condition matches. Replaces the prior 500ms polling loop
        (~120 CDP roundtrips per 30s wait) with one Runtime.evaluate call.

        Returns a snapshot dict ``{tag, id, classes, text, box}`` when matched,
        or ``None`` on timeout.
        """
        import json as _json

        text_check = _json.dumps(text_content or "")
        js = (
            "(async () => {"
            "  const sel = %s;"
            "  const wantVisible = %s;"
            "  const wantText = %s;"
            "  const deadline = performance.now() + %d;"
            "  function match(el) {"
            "    if (!el) return null;"
            "    if (wantVisible) {"
            "      const s = window.getComputedStyle(el);"
            "      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return null;"
            "      const r = el.getBoundingClientRect();"
            "      if (r.width === 0 || r.height === 0) return null;"
            "    }"
            "    if (wantText && !(el.innerText || el.textContent || '').includes(wantText)) return null;"
            "    return el;"
            "  }"
            "  function snapshot(el) {"
            "    const r = el.getBoundingClientRect();"
            "    return {"
            "      tag: el.tagName ? el.tagName.toLowerCase() : null,"
            "      id: el.id || null,"
            "      classes: (el.className && el.className.toString && el.className.toString().split(' ')) || [],"
            "      text: (el.innerText || el.textContent || '').slice(0, 200),"
            "      box: {x: r.x, y: r.y, w: r.width, h: r.height},"
            "    };"
            "  }"
            "  return new Promise((resolve) => {"
            "    const found = match(document.querySelector(sel));"
            "    if (found) return resolve(snapshot(found));"
            "    let resolved = false;"
            "    const obs = new MutationObserver(() => {"
            "      if (resolved) return;"
            "      const hit = match(document.querySelector(sel));"
            "      if (hit) { resolved = true; obs.disconnect(); resolve(snapshot(hit)); }"
            "    });"
            "    obs.observe(document.documentElement, {childList: true, subtree: true, attributes: true});"
            "    const tick = () => {"
            "      if (resolved) return;"
            "      if (performance.now() > deadline) { resolved = true; obs.disconnect(); resolve(null); return; }"
            "      const hit = match(document.querySelector(sel));"
            "      if (hit) { resolved = true; obs.disconnect(); resolve(snapshot(hit)); return; }"
            "      setTimeout(tick, 250);"
            "    };"
            "    setTimeout(tick, 250);"
            "  });"
            "})()"
        ) % (_json.dumps(selector), "true" if visible else "false", text_check, int(timeout))
        try:
            result = await tab.evaluate(js, await_promise=True)
            return result if isinstance(result, dict) else None
        except Exception as exc:
            debug_logger.log_error("dom_handler", "wait_for_element", exc)
            return None

    @staticmethod
    async def execute_script(
        tab: Tab,
        script: str,
        args: Optional[List[Any]] = None
    ) -> Any:
        """
        Execute JavaScript in page context.

        Args:
            tab (Tab): The browser tab object.
            script (str): JavaScript code to execute.
            args (Optional[List[Any]]): Arguments for the script.

        Returns:
            Any: Result of script execution.
        """
        try:
            if args:
                result = await tab.evaluate(f'(function() {{ {script} }})({",".join(map(str, args))})')
            else:
                result = await tab.evaluate(script)

            return result

        except Exception as e:
            raise Exception(f"Failed to execute script: {str(e)}")

    @staticmethod
    async def get_page_content(
        tab: Tab,
        include_frames: bool = False
    ) -> Dict[str, str]:
        """
        Get page HTML and text content.

        Args:
            tab (Tab): The browser tab object.
            include_frames (bool): Include iframe contents.

        Returns:
            Dict[str, str]: Dictionary with page content.
        """
        try:
            html = await tab.get_content()
            text = await tab.evaluate("document.body.innerText")

            content = {
                'html': html,
                'text': text,
                'url': await tab.evaluate("window.location.href"),
                'title': await tab.evaluate("document.title")
            }

            if include_frames:
                frames = []
                iframe_elements = await tab.select_all('iframe')

                for i, iframe in enumerate(iframe_elements):
                    try:
                        src = iframe.attrs.get('src') if hasattr(iframe, 'attrs') else None
                        if src:
                            frames.append({
                                'index': i,
                                'src': src,
                                'id': iframe.attrs.get('id') if hasattr(iframe, 'attrs') else None,
                                'name': iframe.attrs.get('name') if hasattr(iframe, 'attrs') else None
                            })
                    except Exception:
                        continue

                content['frames'] = frames

            return content

        except Exception as e:
            raise Exception(f"Failed to get page content: {str(e)}")

    @staticmethod
    async def scroll_page(
        tab: Tab,
        direction: str = "down",
        amount: int = 500,
        smooth: bool = True
    ) -> bool:
        """
        Scroll the page in specified direction.

        Args:
            tab (Tab): The browser tab object.
            direction (str): Direction to scroll ('down', 'up', 'right', 'left', 'top', 'bottom').
            amount (int): Amount to scroll in pixels.
            smooth (bool): Use smooth scrolling.

        Returns:
            bool: True if scroll succeeded, False otherwise.
        """
        try:
            if direction == "down":
                script = f"window.scrollBy(0, {amount})"
            elif direction == "up":
                script = f"window.scrollBy(0, -{amount})"
            elif direction == "right":
                script = f"window.scrollBy({amount}, 0)"
            elif direction == "left":
                script = f"window.scrollBy(-{amount}, 0)"
            elif direction == "top":
                script = "window.scrollTo(0, 0)"
            elif direction == "bottom":
                script = "window.scrollTo(0, document.body.scrollHeight)"
            else:
                raise ValueError(f"Invalid scroll direction: {direction}")

            if smooth:
                script = script.replace("scrollBy", "scrollBy({behavior: 'smooth'}, ")
                script = script.replace("scrollTo", "scrollTo({behavior: 'smooth', top: ")
                if "scrollTo" in script:
                    script = script.replace(")", "})")

            await tab.evaluate(script)
            await asyncio.sleep(0.5 if smooth else 0.1)

            return True

        except Exception as e:
            raise Exception(f"Failed to scroll page: {str(e)}")