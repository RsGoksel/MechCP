"""UA → client-hints metadata parser produces a consistent UA + Sec-CH-UA tuple."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


def test_parse_known_windows_chrome_ua():
    from stealth_scripts import parse_user_agent_metadata

    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    meta = parse_user_agent_metadata(ua)
    assert meta["platform"] == "Windows"
    assert meta["platform_version"].startswith("10")
    assert meta["architecture"] == "x86"
    assert meta["bitness"] == "64"
    assert meta["mobile"] is False
    assert any(b["brand"] == "Google Chrome" and b["version"] == "126" for b in meta["brands"])


def test_parse_known_mac_chrome_ua():
    from stealth_scripts import parse_user_agent_metadata

    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    meta = parse_user_agent_metadata(ua)
    assert meta["platform"] == "macOS"
    assert meta["mobile"] is False


def test_parse_android_chrome_ua_is_mobile():
    from stealth_scripts import parse_user_agent_metadata

    ua = (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
    )
    meta = parse_user_agent_metadata(ua)
    assert meta["platform"] == "Android"
    assert meta["mobile"] is True


def test_parse_unknown_ua_returns_none_for_overrides():
    from stealth_scripts import parse_user_agent_metadata

    meta = parse_user_agent_metadata("CompletelyMadeUpAgent/1.0")
    # Returns None so the caller does NOT attempt set_user_agent_override
    # with metadata (which would mismatch).
    assert meta is None
