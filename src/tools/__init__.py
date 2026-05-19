"""tools/ package -- per-domain decomposition of the historical server.py monolith.

Phase A: only the ``tabs`` section has been migrated. The remaining sections
still live in ``server.py``. ``register_all`` registers every migrated section
with the FastMCP instance, honoring ``disabled``.

To migrate another section in a follow-up commit:

1. Copy the tool functions out of ``server.py`` into ``tools/<section>.py``
   inside a ``def register(mcp): ...`` wrapper. Replace the
   ``@section_tool("X")`` decorator with ``@section_tool(mcp, "X")``.
2. Append the new module to ``_MODULES`` below.
3. Delete the original tool definitions from ``server.py``.
4. Run the smoke + section-isolation tests.
"""

from __future__ import annotations

from typing import Iterable

from fastmcp import FastMCP

from . import browser, debugging, network, storage, tabs
from ._helpers import disable_sections

_MODULES = [browser, debugging, network, storage, tabs]


def register_all(mcp: FastMCP, disabled: Iterable[str] = ()) -> None:
    """Register every migrated section's tools on ``mcp``, honoring ``disabled``."""
    if disabled:
        disable_sections(disabled)
    for module in _MODULES:
        module.register(mcp)


__all__ = ["register_all"]
