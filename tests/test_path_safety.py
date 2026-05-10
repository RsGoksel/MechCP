"""path_safety blocks traversal and absolute-path escapes."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


def test_safe_join_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("MECHCP_OUTPUT_DIR", str(tmp_path))
    from path_safety import safe_join

    target = safe_join("../../etc/passwd")
    assert tmp_path in target.parents
    assert target.name == "passwd"


def test_safe_join_strips_absolute_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("MECHCP_OUTPUT_DIR", str(tmp_path))
    from path_safety import safe_join

    target = safe_join("/etc/shadow")
    assert tmp_path in target.parents
    assert target.name == "shadow"


def test_safe_join_enforces_allowed_suffixes(tmp_path, monkeypatch):
    monkeypatch.setenv("MECHCP_OUTPUT_DIR", str(tmp_path))
    from path_safety import safe_join

    with pytest.raises(ValueError):
        safe_join("snapshot.exe", allowed_suffixes={".png", ".jpg"})


def test_sanitize_filename_replaces_separators():
    from path_safety import sanitize_filename

    assert sanitize_filename("../../foo/bar.txt") == "bar.txt"
    assert sanitize_filename("") == "output"
