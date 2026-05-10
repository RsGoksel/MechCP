"""Test fixtures shared across the suite.

The smoke tests do not spawn real browsers. They verify that every module
imports cleanly, every MCP tool registers with FastMCP without raising, and
that the security helpers (safe_code, path_safety) reject obvious attacks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"


@pytest.fixture(autouse=True)
def _sandbox_env(tmp_path, monkeypatch):
    """Point MECHCP_OUTPUT_DIR at a per-test tmp dir so file-write tools stay isolated."""
    monkeypatch.setenv("MECHCP_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("MECHCP_LOG_LEVEL", "ERROR")
    yield


@pytest.fixture
def src_on_path():
    """Some tests need src/ importable directly (server.py uses sibling imports)."""
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    yield
