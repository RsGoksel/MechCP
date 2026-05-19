"""Advanced element cloning system with complete styling and JS extraction."""

import asyncio
import functools
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import urljoin, urlparse

import requests

try:
    from .debug_logger import debug_logger
except ImportError:
    from debug_logger import debug_logger


_JS_DIR = Path(__file__).parent / "js"


@functools.lru_cache(maxsize=32)
def _read_js_template(filename: str) -> str:
    """Read a JS template once and cache it for the lifetime of the process.

    The cloner previously re-read these files on every call, which meant a
    single ``clone_element_complete`` call paid 6 sync disk reads on the
    asyncio thread. Caching brings that down to one read per file ever.
    """
    js_file = _JS_DIR / filename
    if not js_file.exists():
        raise FileNotFoundError(f"JavaScript file not found: {js_file}")
    return js_file.read_text(encoding="utf-8")

class ElementCloner:
    """Advanced element cloning with full fidelity extraction."""

    def __init__(self):
        self.extracted_files = {}
        self.framework_patterns = {
            'react': [r'_react', r'__reactInternalInstance', r'__reactFiber'],
            'vue': [r'__vue__', r'_vnode', r'$el'],
            'angular': [r'ng-', r'__ngContext__', r'ɵ'],
            'jquery': [r'jQuery', r'\$\.', r'__jquery']
        }

    async def extract_element_styles(
        self,
        tab,
        element=None,
        selector: str = None,
        include_computed: bool = True,
        include_css_rules: bool = True,
        include_pseudo: bool = True,
        include_inheritance: bool = False
    ) -> Dict[str, Any]:
        """
        Extract complete styling information from an element.

        Args:
            tab (Any): Browser tab instance
            element (Any): Element object or None to use selector
            selector (str): CSS selector if element is None
            include_computed (bool): Include computed styles
            include_css_rules (bool): Include matching CSS rules
            include_pseudo (bool): Include pseudo-element styles
            include_inheritance (bool): Include style inheritance chain

        Returns:
            Dict[str, Any]: Dict with styling data
        """
        try:
            return await self.extract_element_styles_cdp(
                tab=tab,
                element=element,
                selector=selector,
                include_computed=include_computed,
                include_css_rules=include_css_rules,
                include_pseudo=include_pseudo,
                include_inheritance=include_inheritance
            )
        except Exception as e:
            debug_logger.log_error("element_cloner", "extract_styles", e)
            return {"error": str(e)}

    def _load_js_file(self, filename: str, selector: str, options: dict) -> str:
        """Apply selector + options template substitution to a cached JS template."""
        js_code = _read_js_template(filename)
        js_code = js_code.replace('$SELECTOR$', selector)
        js_code = js_code.replace('$SELECTOR', selector)
        js_code = js_code.replace('$OPTIONS$', json.dumps(options))
        js_code = js_code.replace('$OPTIONS', json.dumps(options))

        for key, value in options.items():
            placeholder_key = f'${key.upper()}'
            placeholder_value = 'true' if value else 'false'
            js_code = js_code.replace(placeholder_key, placeholder_value)

        return js_code

    def _convert_nodriver_result(self, data):
        """Convert nodriver's array format back to dict"""
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
            result = {}
            for item in data:
                if isinstance(item, list) and len(item) == 2:
                    key = item[0]
                    value_obj = item[1]
                    if isinstance(value_obj, dict) and 'type' in value_obj:
                        if value_obj['type'] == 'string':
                            result[key] = value_obj.get('value', '')
                        elif value_obj['type'] == 'number':
                            result[key] = value_obj.get('value', 0)
                        elif value_obj['type'] == 'null':
                            result[key] = None
                        elif value_obj['type'] == 'array':
                            result[key] = value_obj.get('value', [])
                        elif value_obj['type'] == 'object':
                            result[key] = self._convert_nodriver_result(value_obj.get('value', []))
                        else:
                            result[key] = value_obj.get('value')
                    else:
                        result[key] = value_obj
            return result
        return data

    async def extract_element_structure(
        self,
        tab,
        element=None,
        selector: str = None,
        include_children: bool = False,
        include_attributes: bool = True,
        include_data_attributes: bool = True,
        max_depth: int = 3
    ) -> Dict[str, Any]:
        """
        Extract complete HTML structure and DOM information.

        Args:
            tab (Any): Browser tab instance
            element (Any): Element object or None to use selector
            selector (str): CSS selector if element is None
            include_children (bool): Include child elements
            include_attributes (bool): Include all attributes
            include_data_attributes (bool): Include data-* attributes specifically
            max_depth (int): Maximum depth for children extraction

        Returns:
            Dict[str, Any]: Dict with structure data
        """
        try:
            if not selector:
                return {"error": "Selector is required"}
                
            options = {
                'include_children': include_children,
                'include_attributes': include_attributes,
                'include_data_attributes': include_data_attributes,
                'max_depth': max_depth
            }
            
            js_code = self._load_js_file('extract_structure.js', selector, options)
            structure_data = await tab.evaluate(js_code)
            
            if hasattr(structure_data, 'exception_details'):
                return {"error": f"JavaScript error: {structure_data.exception_details}"}
            elif isinstance(structure_data, dict):
                debug_logger.log_info("element_cloner", "extract_structure", f"Extracted structure for {structure_data.get('tag_name', 'unknown')} element")
                return structure_data
            elif isinstance(structure_data, list):
                result = self._convert_nodriver_result(structure_data)
                debug_logger.log_info("element_cloner", "extract_structure", f"Extracted structure for {result.get('tag_name', 'unknown')} element")
                return result
            else:
                debug_logger.log_warning("element_cloner", "extract_structure", f"Got unexpected type: {type(structure_data)}")
                return {"error": f"Unexpected return type: {type(structure_data)}", "raw_data": str(structure_data)}
        except Exception as e:
            debug_logger.log_error("element_cloner", "extract_structure", e)
            return {"error": str(e)}

    async def extract_element_events(
        self,
        tab,
        element=None,
        selector: str = None,
        include_inline: bool = True,
        include_listeners: bool = True,
        include_framework: bool = True,
        analyze_handlers: bool = True
    ) -> Dict[str, Any]:
        """
        Extract complete event listener and JavaScript handler information.

        Args:
            tab (Any): Browser tab instance
            element (Any): Element object or None to use selector
            selector (str): CSS selector if element is None
            include_inline (bool): Include inline event handlers (onclick, etc.)
            include_listeners (bool): Include addEventListener attached handlers
            include_framework (bool): Include framework-specific handlers (React, Vue, etc.)
            analyze_handlers (bool): Analyze handler functions for details

        Returns:
            Dict[str, Any]: Dict with event data
        """
        try:
            if not selector:
                return {"error": "Selector is required"}
                
            options = {
                'include_inline': include_inline,
                'include_listeners': include_listeners,
                'include_framework': include_framework,
                'analyze_handlers': analyze_handlers
            }
            
            js_code = self._load_js_file('extract_events.js', selector, options)
            event_data = await tab.evaluate(js_code)
            
            if hasattr(event_data, 'exception_details'):
                return {"error": f"JavaScript error: {event_data.exception_details}"}
            elif isinstance(event_data, dict):
                debug_logger.log_info("element_cloner", "extract_events", f"Extracted events for element")
                return event_data
            elif isinstance(event_data, list):
                result = self._convert_nodriver_result(event_data)
                debug_logger.log_info("element_cloner", "extract_events", f"Extracted events for element")
                return result
            else:
                debug_logger.log_warning("element_cloner", "extract_events", f"Got unexpected type: {type(event_data)}")
                return {"error": f"Unexpected return type: {type(event_data)}", "raw_data": str(event_data)}
        except Exception as e:
            debug_logger.log_error("element_cloner", "extract_events", e)
            return {"error": str(e)}

    async def extract_element_animations(
        self,
        tab,
        element=None,
        selector: str = None,
        include_css_animations: bool = True,
        include_transitions: bool = True,
        include_transforms: bool = True,
        analyze_keyframes: bool = True
    ) -> Dict[str, Any]:
        """
        Extract CSS animations, transitions, and transforms.

        Args:
            tab (Any): Browser tab instance
            element (Any): Element object or None to use selector
            selector (str): CSS selector if element is None
            include_css_animations (bool): Include CSS @keyframes animations
            include_transitions (bool): Include CSS transitions
            include_transforms (bool): Include CSS transforms
            analyze_keyframes (bool): Analyze keyframe rules

        Returns:
            Dict[str, Any]: Dict with animation data
        """
        try:
            if not selector:
                return {"error": "Selector is required"}
                
            options = {
                'include_css_animations': include_css_animations,
                'include_transitions': include_transitions,
                'include_transforms': include_transforms,
                'analyze_keyframes': analyze_keyframes
            }
            
            js_code = self._load_js_file('extract_animations.js', selector, options)
            animation_data = await tab.evaluate(js_code)
            
            if hasattr(animation_data, 'exception_details'):
                return {"error": f"JavaScript error: {animation_data.exception_details}"}
            elif isinstance(animation_data, dict):
                debug_logger.log_info("element_cloner", "extract_animations", f"Extracted animations for element")
                return animation_data
            elif isinstance(animation_data, list):
                result = self._convert_nodriver_result(animation_data)
                debug_logger.log_info("element_cloner", "extract_animations", f"Extracted animations for element")
                return result
            else:
                debug_logger.log_warning("element_cloner", "extract_animations", f"Got unexpected type: {type(animation_data)}")
                return {"error": f"Unexpected return type: {type(animation_data)}", "raw_data": str(animation_data)}
        except Exception as e:
            debug_logger.log_error("element_cloner", "extract_animations", e)
            return {"error": str(e)}

    async def extract_element_assets(
        self,
        tab,
        element=None,
        selector: str = None,
        include_images: bool = True,
        include_backgrounds: bool = True,
        include_fonts: bool = True,
        fetch_external: bool = False
    ) -> Dict[str, Any]:
        """
        Extract all assets related to an element (images, fonts, etc.).

        Args:
            tab (Any): Browser tab instance
            element (Any): Element object or None to use selector
            selector (str): CSS selector if element is None
            include_images (bool): Include img src and related images
            include_backgrounds (bool): Include background images
            include_fonts (bool): Include font information
            fetch_external (bool): Whether to fetch external assets for analysis

        Returns:
            Dict[str, Any]: Dict with asset data
        """
        try:
            if not selector:
                return {"error": "Selector is required"}
                
            try:
                js_code = _read_js_template("extract_assets.js")
            except FileNotFoundError as exc:
                return {"error": str(exc)}

            js_code = js_code.replace('$SELECTOR', selector)
            js_code = js_code.replace('$INCLUDE_IMAGES', 'true' if include_images else 'false')
            js_code = js_code.replace('$INCLUDE_BACKGROUNDS', 'true' if include_backgrounds else 'false')
            js_code = js_code.replace('$INCLUDE_FONTS', 'true' if include_fonts else 'false')
            js_code = js_code.replace('$FETCH_EXTERNAL', 'true' if fetch_external else 'false')
            
            asset_data = await tab.evaluate(js_code)
            if hasattr(asset_data, 'exception_details'):
                return {"error": f"JavaScript error: {asset_data.exception_details}"}
            elif isinstance(asset_data, dict):
                pass
            elif isinstance(asset_data, list):
                # Convert nodriver's array format back to dict
                asset_data = self._convert_nodriver_result(asset_data)
            else:
                debug_logger.log_warning("element_cloner", "extract_assets", f"Got unexpected type: {type(asset_data)}")
                return {"error": f"Unexpected return type: {type(asset_data)}", "raw_data": str(asset_data)}
            
            if fetch_external and isinstance(asset_data, dict):
                bg_urls = [
                    bg.get('url', '')
                    for bg in asset_data.get('background_images', [])
                    if bg.get('url', '').startswith('http')
                ]
                asset_data['external_assets'] = await self._fetch_asset_metadata(bg_urls, tab=tab)
            
            debug_logger.log_info("element_cloner", "extract_assets", f"Extracted assets for element")
            return asset_data
        except Exception as e:
            debug_logger.log_error("element_cloner", "extract_assets", e)
            return {"error": str(e)}

    async def extract_related_files(
        self,
        tab,
        element=None,
        selector: str = None,
        analyze_css: bool = True,
        analyze_js: bool = True,
        follow_imports: bool = False,
        max_depth: int = 2
    ) -> Dict[str, Any]:
        """
        Discover and analyze related CSS/JS files for context.

        Args:
            tab (Any): Browser tab instance
            element (Any): Element object or None to use selector
            selector (str): CSS selector if element is None
            analyze_css (bool): Analyze linked CSS files
            analyze_js (bool): Analyze linked JS files
            follow_imports (bool): Follow @import and module imports
            max_depth (int): Maximum depth for following imports

        Returns:
            Dict[str, Any]: Dict with related file data
        """
        try:
            try:
                js_code = _read_js_template("extract_related_files.js")
            except FileNotFoundError as exc:
                return {"error": str(exc)}

            js_code = js_code.replace('$ANALYZE_CSS', 'true' if analyze_css else 'false')
            js_code = js_code.replace('$ANALYZE_JS', 'true' if analyze_js else 'false')
            js_code = js_code.replace('$FOLLOW_IMPORTS', 'true' if follow_imports else 'false')
            js_code = js_code.replace('$MAX_DEPTH', str(max_depth))
            
            file_data = await tab.evaluate(js_code)
            if hasattr(file_data, 'exception_details'):
                return {"error": f"JavaScript error: {file_data.exception_details}"}
            elif isinstance(file_data, dict):
                pass
            elif isinstance(file_data, list):
                file_data = self._convert_nodriver_result(file_data)
            else:
                debug_logger.log_warning("element_cloner", "extract_related_files", f"Got unexpected type: {type(file_data)}")
                return {"error": f"Unexpected return type: {type(file_data)}", "raw_data": str(file_data)}
            
            if follow_imports and max_depth > 0 and isinstance(file_data, dict):
                await self._fetch_and_analyze_files(file_data, tab.url, max_depth, tab=tab)
            
            debug_logger.log_info("element_cloner", "extract_related_files", f"Found related files")
            return file_data
        except Exception as e:
            debug_logger.log_error("element_cloner", "extract_related_files", e)
            return {"error": str(e)}

    async def _fetch_via_tab(self, tab, url: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """Fetch ``url`` inside the page context so the origin sees the page's TLS fingerprint.

        Returns ``{status, text, headers}`` on success, None on failure. Used to
        avoid having two separate JA3 signatures (Chrome + Python ``requests``)
        hitting the same origin from the same client, which is trivially
        correlatable by anti-bot systems.
        """
        if not tab:
            return None
        js = (
            "(async () => {"
            "  const r = await fetch(%s, {credentials: 'include', mode: 'cors'});"
            "  const text = await r.text();"
            "  const headers = {};"
            "  r.headers.forEach((v, k) => { headers[k] = v; });"
            "  return {status: r.status, text, headers};"
            "})()"
        ) % json.dumps(url)
        try:
            return await asyncio.wait_for(tab.evaluate(js, await_promise=True), timeout=timeout)
        except Exception as exc:
            debug_logger.log_warning(
                "element_cloner",
                "_fetch_via_tab",
                f"page-context fetch failed for {url}: {exc}",
            )
            return None

    async def _fetch_url_text(self, url: str, timeout: int = 10, tab=None) -> Optional[Dict[str, Any]]:
        """Fetch a URL and return status/text/headers.

        Prefers the in-page ``fetch`` (so JA3 / cookies match the current
        browsing session). Falls back to Python's ``requests`` if the tab
        rejects the script (e.g. CSP). The fallback is async-safe.
        """
        if tab is not None:
            result = await self._fetch_via_tab(tab, url, timeout=float(timeout))
            if result is not None:
                return result
        try:
            response = await asyncio.to_thread(requests.get, url, timeout=timeout)
            return {"status": response.status_code, "text": response.text, "headers": dict(response.headers)}
        except Exception as exc:
            debug_logger.log_warning(
                "element_cloner",
                "_fetch_url_text",
                f"could not fetch {url}: {exc}",
            )
            return None

    async def _fetch_asset_metadata(self, urls: List[str], tab=None) -> Dict[str, Dict[str, Any]]:
        """Fetch asset URLs concurrently. Prefers in-page fetch for stealth."""
        if not urls:
            return {}

        sem = asyncio.Semaphore(8)

        async def fetch_one(url: str) -> tuple[str, Optional[Dict[str, Any]]]:
            async with sem:
                if tab is not None:
                    result = await self._fetch_via_tab(tab, url, timeout=5.0)
                    if result is not None:
                        return url, {
                            "content_type": (result.get("headers") or {}).get("content-type"),
                            "size": len(result.get("text", "")),
                            "status": result.get("status"),
                        }
                try:
                    response = await asyncio.to_thread(requests.get, url, timeout=5)
                    return url, {
                        "content_type": response.headers.get("content-type"),
                        "size": len(response.content),
                        "status": response.status_code,
                    }
                except Exception as exc:
                    debug_logger.log_warning(
                        "element_cloner",
                        "_fetch_asset_metadata",
                        f"could not fetch asset {url}: {exc}",
                    )
                    return url, None

        results = await asyncio.gather(*(fetch_one(u) for u in urls))
        return {url: meta for url, meta in results if meta is not None}

    async def _fetch_and_analyze_files(self, file_data: Dict, base_url: str, max_depth: int, tab=None) -> None:
        """Fetch external CSS/JS in parallel without blocking the event loop."""

        async def process_stylesheet(stylesheet: Dict[str, Any]) -> None:
            href = stylesheet.get('href')
            if not href or href in self.extracted_files:
                return
            fetched = await self._fetch_url_text(href, timeout=10, tab=tab)
            if not fetched or fetched["status"] != 200:
                return
            content = fetched["text"]
            self.extracted_files[href] = content
            imports = re.findall(r'@import\s+["\']([^"\']+)["\']', content)
            stylesheet['imports'] = [urljoin(href, imp) for imp in imports]
            stylesheet['custom_properties'] = re.findall(r'--[\w-]+:\s*[^;]+', content)

        async def process_script(script: Dict[str, Any]) -> None:
            src = script.get('src')
            if not src or src in self.extracted_files:
                return
            fetched = await self._fetch_url_text(src, timeout=10, tab=tab)
            if not fetched or fetched["status"] != 200:
                return
            content = fetched["text"]
            self.extracted_files[src] = content
            detected: List[str] = []
            for framework, patterns in self.framework_patterns.items():
                if any(re.search(p, content, re.IGNORECASE) for p in patterns):
                    detected.append(framework)
            script['detected_frameworks'] = detected
            script['module_imports'] = re.findall(r'import.*from\s+["\']([^"\']+)["\']', content)

        await asyncio.gather(
            *(process_stylesheet(s) for s in file_data.get('stylesheets', [])),
            *(process_script(s) for s in file_data.get('scripts', [])),
        )

    async def clone_element_complete(
        self,
        tab,
        element=None,
        selector: str = None,
        extraction_options: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Master function that extracts all element data using specialized functions.

        Args:
            tab (Any): Browser tab instance
            element (Any): Element object or None to use selector
            selector (str): CSS selector if element is None
            extraction_options (Dict[str, Any]): Dict specifying what to extract and options for each
                Example: {
                    'styles': {'include_computed': True, 'include_pseudo': True},
                    'structure': {'include_children': True, 'max_depth': 2},
                    'events': {'include_framework': True, 'analyze_handlers': True},
                    'animations': {'analyze_keyframes': True},
                    'assets': {'fetch_external': True},
                    'related_files': {'follow_imports': True, 'max_depth': 1}
                }

        Returns:
            Dict[str, Any]: Complete element clone data
        """
        try:
            default_options = {
                'styles': {'include_computed': True, 'include_css_rules': True, 'include_pseudo': True},
                'structure': {'include_children': False, 'include_attributes': True},
                'events': {'include_framework': True, 'analyze_handlers': False},
                'animations': {'analyze_keyframes': True},
                'assets': {'fetch_external': False},
                'related_files': {'follow_imports': False}
            }
            if extraction_options:
                for key, value in extraction_options.items():
                    if key in default_options:
                        default_options[key].update(value)
                    else:
                        default_options[key] = value
            if element is None and selector:
                element = await tab.select(selector)
            if not element:
                return {"error": "Element not found"}
            result = {
                "url": tab.url,
                "timestamp": asyncio.get_event_loop().time(),
                "selector": selector,
                "extraction_options": default_options
            }
            tasks = []
            if 'styles' in default_options:
                tasks.append(('styles', self.extract_element_styles(tab, element, **default_options['styles'])))
            if 'structure' in default_options:
                tasks.append(('structure', self.extract_element_structure(tab, element, **default_options['structure'])))
            if 'events' in default_options:
                tasks.append(('events', self.extract_element_events(tab, element, **default_options['events'])))
            if 'animations' in default_options:
                tasks.append(('animations', self.extract_element_animations(tab, element, **default_options['animations'])))
            if 'assets' in default_options:
                tasks.append(('assets', self.extract_element_assets(tab, element, **default_options['assets'])))
            if 'related_files' in default_options:
                tasks.append(('related_files', self.extract_related_files(tab, **default_options['related_files'])))
            results = await asyncio.gather(*[task[1] for task in tasks], return_exceptions=True)
            for i, (name, _) in enumerate(tasks):
                if isinstance(results[i], Exception):
                    result[name] = {"error": str(results[i])}
                else:
                    result[name] = results[i]
            debug_logger.log_info("element_cloner", "clone_complete", f"Complete element clone extracted with {len(tasks)} data types")
            return result
        except Exception as e:
            debug_logger.log_error("element_cloner", "clone_complete", e)
            return {"error": str(e)}

    async def extract_element_styles_cdp(
        self,
        tab,
        element=None,
        selector: str = None,
        include_computed: bool = True,
        include_css_rules: bool = True,
        include_pseudo: bool = True,
        include_inheritance: bool = False
    ) -> Dict[str, Any]:
        """
        Extract complete styling information using direct CDP calls (no JavaScript evaluation).
        This prevents hanging issues by using nodriver's native CDP methods.

        Args:
            tab (Any): Browser tab instance
            element (Any): Element object or None to use selector
            selector (str): CSS selector if element is None
            include_computed (bool): Include computed styles
            include_css_rules (bool): Include matching CSS rules
            include_pseudo (bool): Include pseudo-element styles
            include_inheritance (bool): Include style inheritance chain

        Returns:
            Dict[str, Any]: Dict with styling data
        """
        try:
            import nodriver.cdp as cdp
            
            await tab.send(cdp.dom.enable())
            await tab.send(cdp.css.enable())
            
            if element is None and selector:
                element = await tab.select(selector)
            if not element:
                return {"error": "Element not found"}
            
            if hasattr(element, 'node_id'):
                node_id = element.node_id
            elif hasattr(element, 'backend_node_id'):
                node_info = await tab.send(cdp.dom.describe_node(backend_node_id=element.backend_node_id))
                node_id = node_info.node.node_id
            else:
                return {"error": "Could not get node ID from element"}
            
            result = {"method": "cdp_direct"}
            
            if include_computed:
                debug_logger.log_info("element_cloner", "extract_styles_cdp", "Getting computed styles via CDP")
                computed_styles_list = await tab.send(cdp.css.get_computed_style_for_node(node_id))
                result["computed_styles"] = {prop.name: prop.value for prop in computed_styles_list}
                
            if include_css_rules:
                debug_logger.log_info("element_cloner", "extract_styles_cdp", "Getting matched styles via CDP")
                matched_styles = await tab.send(cdp.css.get_matched_styles_for_node(node_id))
                
                # Extract CSS rules from matched styles
                result["css_rules"] = []
                if matched_styles[2]:  # matchedCSSRules
                    for rule_match in matched_styles[2]:
                        if rule_match.rule and rule_match.rule.style:
                            result["css_rules"].append({
                                "selector": rule_match.rule.selector_list.text if rule_match.rule.selector_list else "unknown",
                                "css_text": rule_match.rule.style.css_text or "",
                                "source": rule_match.rule.origin.value if rule_match.rule.origin else "unknown"
                            })
                
                # Add inline styles if present
                if matched_styles[0]:  # inlineStyle
                    result["inline_style"] = {
                        "css_text": matched_styles[0].css_text or "",
                        "properties": len(matched_styles[0].css_properties) if matched_styles[0].css_properties else 0
                    }
                    
                # Add attribute styles if present  
                if matched_styles[1]:  # attributesStyle
                    result["attributes_style"] = {
                        "css_text": matched_styles[1].css_text or "",
                        "properties": len(matched_styles[1].css_properties) if matched_styles[1].css_properties else 0
                    }
            
            # Handle pseudo elements (if available in matched_styles)
            if include_pseudo and len(matched_styles) > 3 and matched_styles[3]:
                result["pseudo_elements"] = {}
                for pseudo_match in matched_styles[3]:
                    if pseudo_match.pseudo_type:
                        result["pseudo_elements"][pseudo_match.pseudo_type.value] = {
                            "matches": len(pseudo_match.matches) if pseudo_match.matches else 0
                        }
            
            # Handle inheritance (if available in matched_styles)
            if include_inheritance and len(matched_styles) > 4 and matched_styles[4]:
                result["inheritance_chain"] = []
                for inherited_entry in matched_styles[4]:
                    if inherited_entry.inline_style:
                        result["inheritance_chain"].append({
                            "inline_css": inherited_entry.inline_style.css_text or "",
                            "properties": len(inherited_entry.inline_style.css_properties) if inherited_entry.inline_style.css_properties else 0
                        })
            
            debug_logger.log_info("element_cloner", "extract_styles_cdp", f"CDP extraction completed with {len(result.get('css_rules', []))} CSS rules")
            return result
            
        except Exception as e:
            debug_logger.log_error("element_cloner", "extract_styles_cdp", e)
            return {"error": f"CDP extraction failed: {str(e)}"}

element_cloner = ElementCloner()
