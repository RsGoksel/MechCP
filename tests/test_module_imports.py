"""Every module under src/ imports cleanly, with no ImportError or stray prints to stdout."""

from __future__ import annotations

import importlib
import io
import sys
from contextlib import redirect_stdout

import pytest

MODULES = [
    "safe_code",
    "path_safety",
    "debug_logger",
    "models",
    "platform_utils",
    "process_cleanup",
    "persistent_storage",
    "response_handler",
    "browser_manager",
    "network_interceptor",
    "dom_handler",
    "dynamic_hook_system",
    "dynamic_hook_ai_interface",
    "hook_learning_system",
    "cdp_function_executor",
    "cdp_element_cloner",
    "comprehensive_element_cloner",
    "element_cloner",
    "file_based_element_cloner",
    "progressive_element_cloner",
]


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_cleanly(name):
    sys.modules.pop(name, None)
    buf = io.StringIO()
    with redirect_stdout(buf):
        importlib.import_module(name)
    leaked = buf.getvalue()
    assert leaked == "", (
        f"module {name} wrote to stdout on import: {leaked!r}. "
        "Stdout is reserved for MCP JSON-RPC framing."
    )
