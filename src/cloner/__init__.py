"""Single import point for every element-cloner.

This package will eventually contain a unified implementation, but for
now it is an aggregation shim: it re-exports the legacy singletons under
stable names so callers can transition without behavior change.

The rich JS-eval ``element_cloner`` already implements every method
``server.py`` calls, so it is aliased as ``unified_cloner`` -- the primary
entry point. The other singletons remain reachable for the small number
of callsites that need their specific behavior (file-based persistence,
progressive lazy expansion, comprehensive single-dump).
"""

from element_cloner import element_cloner as _legacy_element_cloner
from comprehensive_element_cloner import (
    comprehensive_element_cloner as _legacy_comprehensive,
)
from file_based_element_cloner import (
    file_based_element_cloner as _legacy_file_based,
)
from progressive_element_cloner import (
    progressive_element_cloner as _legacy_progressive,
)
from cdp_element_cloner import CDPElementCloner

element_cloner = _legacy_element_cloner
comprehensive_element_cloner = _legacy_comprehensive
file_based_element_cloner = _legacy_file_based
progressive_element_cloner = _legacy_progressive
unified_cloner = _legacy_element_cloner  # primary entry; the rich JS-eval one

__all__ = [
    "CDPElementCloner",
    "comprehensive_element_cloner",
    "element_cloner",
    "file_based_element_cloner",
    "progressive_element_cloner",
    "unified_cloner",
]
