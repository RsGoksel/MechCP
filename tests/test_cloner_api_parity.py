"""Parity tests for the cloner aggregation shim.

These tests guarantee that ``cloner.unified_cloner`` exposes every
method that ``server.py`` calls on the legacy ``element_cloner``
singleton, and that the shim re-exports each legacy singleton under
its original name without altering identity.

If a future refactor swaps ``unified_cloner`` for a real merged
implementation, this test still has to pass -- that is the contract.
"""

from __future__ import annotations

import inspect

import pytest


# Methods server.py calls on element_cloner (the singleton aliased as
# unified_cloner). All are async coroutine functions in the current
# implementation. Gathered from src/server.py callsites.
REQUIRED_ASYNC_METHODS = (
    "extract_element_styles",
    "extract_element_structure",
    "extract_element_events",
    "extract_element_animations",
    "extract_element_assets",
    "extract_element_styles_cdp",
    "extract_related_files",
)


def test_unified_cloner_is_legacy_element_cloner(src_on_path):
    """unified_cloner must alias the legacy element_cloner singleton."""
    from cloner import unified_cloner, element_cloner

    assert unified_cloner is element_cloner


def test_unified_cloner_exposes_required_async_methods(src_on_path):
    """Every method server.py calls on element_cloner must remain available."""
    from cloner import unified_cloner

    for name in REQUIRED_ASYNC_METHODS:
        method = getattr(unified_cloner, name, None)
        assert method is not None, f"unified_cloner missing {name!r}"
        assert inspect.iscoroutinefunction(method), (
            f"unified_cloner.{name} must be a coroutine function"
        )


def test_shim_reexports_legacy_singletons(src_on_path):
    """The package must re-export every legacy singleton without renaming it."""
    import cloner
    import element_cloner as _ec_mod
    import comprehensive_element_cloner as _comp_mod
    import file_based_element_cloner as _fb_mod
    import progressive_element_cloner as _prog_mod
    from cdp_element_cloner import CDPElementCloner as _CDPCls

    assert cloner.element_cloner is _ec_mod.element_cloner
    assert cloner.comprehensive_element_cloner is _comp_mod.comprehensive_element_cloner
    assert cloner.file_based_element_cloner is _fb_mod.file_based_element_cloner
    assert cloner.progressive_element_cloner is _prog_mod.progressive_element_cloner
    assert cloner.CDPElementCloner is _CDPCls


def test_shim_all_lists_public_names(src_on_path):
    """__all__ must list exactly the public names callers should depend on."""
    import cloner

    expected = {
        "CDPElementCloner",
        "comprehensive_element_cloner",
        "element_cloner",
        "file_based_element_cloner",
        "progressive_element_cloner",
        "unified_cloner",
    }
    assert set(cloner.__all__) == expected
