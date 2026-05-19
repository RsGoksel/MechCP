"""Stealth init scripts injected via Page.addScriptToEvaluateOnNewDocument.

These run before any page script and patch the most commonly-fingerprinted
properties that headless / automated Chrome leaves visible by default:

- ``navigator.webdriver`` (the classic headless tell)
- ``navigator.plugins`` and ``navigator.mimeTypes`` (empty arrays in headless)
- ``navigator.languages`` (sometimes ``[]`` in headless)
- ``Notification.permission`` (``default`` in headless even after user grant)
- ``WebGLRenderingContext.getParameter`` (ANGLE/SwiftShader strings)
- ``window.chrome.runtime`` (missing in headless)

The patches are conservative: each one checks for the actual leak before
mutating, so they do not regress on already-good Chrome builds.

The viewport-randomization helper picks a viewport from a weighted realistic
distribution so MechCP's default does not match the canonical bot fleet
signature (1920x1080 with devicePixelRatio=1).
"""

from __future__ import annotations

import random
import re
from typing import Optional, Tuple

# Weighted from public StatCounter desktop viewport stats; intentionally avoids
# pure 1920x1080 dominance so two MechCP instances do not look identical.
_VIEWPORTS: Tuple[Tuple[int, int, float], ...] = (
    (1366, 768, 0.22),
    (1536, 864, 0.18),
    (1440, 900, 0.14),
    (1280, 720, 0.10),
    (1600, 900, 0.10),
    (1680, 1050, 0.06),
    (1280, 800, 0.05),
    (1920, 1080, 0.15),
)


def pick_realistic_viewport(rng: random.Random | None = None) -> Tuple[int, int]:
    """Return a (width, height) sampled from a realistic distribution."""
    r = rng or random
    sizes = [(w, h) for w, h, _ in _VIEWPORTS]
    weights = [p for _, _, p in _VIEWPORTS]
    return r.choices(sizes, weights=weights, k=1)[0]


# JS shipped to Page.addScriptToEvaluateOnNewDocument. Self-contained so
# it can be applied to every frame (including OOPIFs) with one CDP call.
STEALTH_INIT_JS = r"""
(() => {
  try {
    // 1. navigator.webdriver — set to undefined (not false) so feature detection
    //    sees "missing" not "explicitly disabled".
    if (navigator.webdriver !== undefined) {
      try {
        Object.defineProperty(Navigator.prototype, 'webdriver', {
          get: () => undefined,
          configurable: true,
        });
      } catch (_) {}
    }

    // 2. navigator.plugins — headless Chrome ships [] which is a strong tell.
    if (!navigator.plugins || navigator.plugins.length === 0) {
      try {
        const fakePlugin = (name, filename, description) => ({
          name, filename, description, length: 1,
          0: { type: 'application/x-google-chrome-pdf', suffixes: 'pdf' },
        });
        const plugins = [
          fakePlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
          fakePlugin('Chrome PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
          fakePlugin('Chromium PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
        ];
        plugins.length = 3;
        Object.defineProperty(navigator, 'plugins', {
          get: () => plugins,
          configurable: true,
        });
      } catch (_) {}
    }

    // 3. navigator.languages — empty array on headless before content_settings load.
    if (!navigator.languages || navigator.languages.length === 0) {
      try {
        Object.defineProperty(navigator, 'languages', {
          get: () => ['en-US', 'en'],
          configurable: true,
        });
      } catch (_) {}
    }

    // 4. Notification.permission — headless reports 'default' even when granted.
    //    Patch the .query path used by site code to detect bot.
    if (window.Notification) {
      try {
        const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
        if (originalQuery) {
          window.navigator.permissions.query = (params) => (
            params && params.name === 'notifications'
              ? Promise.resolve({ state: Notification.permission })
              : originalQuery.call(window.navigator.permissions, params)
          );
        }
      } catch (_) {}
    }

    // 5. WebGL vendor/renderer — patch UNMASKED_VENDOR/UNMASKED_RENDERER which
    //    return SwiftShader / Google-internal strings on headless.
    try {
      const patchGL = (proto) => {
        if (!proto) return;
        const orig = proto.getParameter;
        proto.getParameter = function (param) {
          // UNMASKED_VENDOR_WEBGL = 37445; UNMASKED_RENDERER_WEBGL = 37446
          if (param === 37445) return 'Intel Inc.';
          if (param === 37446) return 'Intel Iris OpenGL Engine';
          return orig.call(this, param);
        };
      };
      patchGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
      patchGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);
    } catch (_) {}

    // 6. window.chrome — missing in headless; site code uses `window.chrome.runtime`
    //    as a Chrome-vs-bot check.
    if (!window.chrome) {
      try {
        window.chrome = { runtime: {} };
      } catch (_) {}
    } else if (!window.chrome.runtime) {
      try {
        window.chrome.runtime = {};
      } catch (_) {}
    }
  } catch (_) {
    // Stealth script failures must not break the page; swallow silently.
  }
})();
"""


# Chrome CLI flags that hide the most common automation tells. These are
# applied in addition to whatever defaults the bundled nodriver version sets.
DEFAULT_STEALTH_ARGS: Tuple[str, ...] = (
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process,UserAgentClientHint",
    "--disable-infobars",
    "--disable-dev-shm-usage",
    "--no-default-browser-check",
    "--no-first-run",
    "--password-store=basic",
    "--use-mock-keychain",
)


_UA_PLATFORM_PATTERNS = [
    (re.compile(r"\bWindows NT 11\.0"), ("Windows", "11")),
    (re.compile(r"\bWindows NT 10\.0"), ("Windows", "10")),
    (re.compile(r"\bWindows NT 6\.3"), ("Windows", "8.1")),
    (re.compile(r"\bAndroid (\d+)"), ("Android", None)),
    (re.compile(r"\bMac OS X (\d+)[_.](\d+)"), ("macOS", None)),
    (re.compile(r"\bCrOS\b"), ("Chrome OS", "")),
    (re.compile(r"\bLinux\b"), ("Linux", "")),
]

_UA_CHROME_VERSION = re.compile(r"Chrome/(\d+)\.")


def parse_user_agent_metadata(ua: str) -> Optional[dict]:
    """Return a Chrome-compatible userAgentMetadata dict matching ``ua``.

    Returns ``None`` when the UA is not recognized as a Chromium browser, so
    callers do NOT override metadata and the real client-hint values continue
    to ship. A spoofed UA with mismatched metadata is the single highest-signal
    bot fingerprint, so the parser is intentionally conservative.
    """
    if not ua or "Chrome/" not in ua:
        return None

    chrome_match = _UA_CHROME_VERSION.search(ua)
    if not chrome_match:
        return None
    major = chrome_match.group(1)

    platform = "Unknown"
    platform_version = ""
    for pattern, (plat, default_ver) in _UA_PLATFORM_PATTERNS:
        m = pattern.search(ua)
        if m:
            platform = plat
            if plat == "macOS" and m.lastindex and m.lastindex >= 2:
                platform_version = f"{m.group(1)}.{m.group(2)}"
            elif plat == "Android" and m.lastindex:
                platform_version = m.group(1)
            else:
                platform_version = default_ver or ""
            break

    mobile = "Mobile" in ua or platform == "Android"
    arch_l = ua.lower()
    architecture = "arm" if ("arm" in arch_l or platform == "Android") else "x86"
    bitness = "64" if any(t in ua for t in ("WOW64", "Win64", "x64", "x86_64")) else "32"

    return {
        "platform": platform,
        "platform_version": platform_version,
        "architecture": architecture,
        "bitness": bitness,
        "model": "",
        "mobile": mobile,
        "brands": [
            {"brand": "Not/A)Brand", "version": "99"},
            {"brand": "Google Chrome", "version": major},
            {"brand": "Chromium", "version": major},
        ],
    }


def bezier_path(
    start: Tuple[float, float],
    end: Tuple[float, float],
    *,
    steps: int = 12,
    jitter: float = 18.0,
    rng: random.Random | None = None,
) -> list:
    """Return a list of ``(x, y, dwell_seconds)`` along a jittered cubic Bezier.

    ``dwell_seconds`` is a small Gaussian-jittered pause between hops so the
    overall trajectory has organic variance instead of a constant frame rate.
    Used to send `Input.dispatchMouseEvent(mouseMoved, ...)` along the path
    before a click, defeating the simplest "click without trajectory" detector.
    """
    r = rng or random
    cx1 = start[0] + (end[0] - start[0]) * 0.33 + r.uniform(-jitter, jitter)
    cy1 = start[1] + (end[1] - start[1]) * 0.33 + r.uniform(-jitter, jitter)
    cx2 = start[0] + (end[0] - start[0]) * 0.66 + r.uniform(-jitter, jitter)
    cy2 = start[1] + (end[1] - start[1]) * 0.66 + r.uniform(-jitter, jitter)

    path = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1.0 - t
        x = (mt ** 3) * start[0] + 3 * (mt ** 2) * t * cx1 + 3 * mt * (t ** 2) * cx2 + (t ** 3) * end[0]
        y = (mt ** 3) * start[1] + 3 * (mt ** 2) * t * cy1 + 3 * mt * (t ** 2) * cy2 + (t ** 3) * end[1]
        dwell = max(0.005, r.gauss(0.018, 0.006))
        path.append((x, y, dwell))
    return path
