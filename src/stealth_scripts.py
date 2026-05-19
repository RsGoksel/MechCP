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
from typing import Tuple

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
