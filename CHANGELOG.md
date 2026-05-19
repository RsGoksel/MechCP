# Changelog

All notable changes to MechCP are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Actions CI workflow running `pytest` + `compileall` across Python 3.10-3.13 on every push and PR.
- CONTRIBUTING.md, SECURITY.md, CHANGELOG.md (standard public-repo docs).
- `query_shadow` MCP tool that pierces open Shadow DOM via `querySelectorDeep`.
- `list_frames` MCP tool that enumerates child iframes with stable frame IDs.
- Optional `frame_id` parameter on `click_element`, `type_text`, and
  `wait_for_element` (per-frame routing scaffolding; resolution surfaces an
  explicit "not yet supported" error until nodriver exposes per-frame Tab
  objects).

### Changed
- Fake-credential examples in `hook_learning_system.py` templates replaced
  with explicit placeholders (`Bearer <REDACTED>`, `<api-key-placeholder>`)
  to avoid tripping naive secret scanners.

## [0.3.0] - 2026-05-19

This is the first published release of the MechCP fork. It supersedes the
upstream `stealth-browser-mcp` codebase with a security and code-quality
pass focused on running AI-supplied code safely on the host.

### Added
- `src/safe_code.py` with an AST validator and sandboxed `safe_compile` for
  every AI-supplied Python path. Blocks imports, dunder access, walrus
  operator, bare `__builtins__` references, and the standard sandbox-escape
  patterns.
- `src/path_safety.py` with `safe_join` and `sanitize_filename` that lock
  every AI-supplied path under `MECHCP_OUTPUT_DIR`.
- `src/stealth_scripts.py` with `STEALTH_INIT_JS` injected via
  `Page.addScriptToEvaluateOnNewDocument` on every spawn:
  `navigator.webdriver`, `plugins`, `languages`, `Notification.permission`,
  WebGL vendor/renderer, and `window.chrome.runtime` are patched before the
  page's first script.
- `DEFAULT_STEALTH_ARGS` applied to `uc.Config` (closes
  `AutomationControlled` and related blink-feature tells).
- Realistic-viewport sampler replaces the bot-fleet 1920x1080 default.
- Gaussian-jittered keystrokes and jittered Bezier mouse trajectory before
  clicks (`type_text`, `click_element`).
- `Sec-CH-UA` client-hints synchronization when the user agent is
  overridden, closing the spoofed-UA-vs-real-client-hints fingerprint gap.
- Real `wait_until="networkidle"` via an in-flight request counter
  (previously a literal 2-second sleep).
- `click_element` returns `{success, navigated, dom_mutated, ...}` instead
  of bare `True`, so agents can verify the click had an effect.
- New token-efficient tools: `get_visible_text`, `get_page_outline`,
  `screenshot_element`, `get_console_logs`.
- `MECHCP_MINIMAL` and `MECHCP_DISABLED_SECTIONS` env vars honored at
  decorator time.
- Vendored `py2js` under `vendor/py2js/` (removes force-push risk from
  the upstream personal fork).
- 57-test pytest smoke suite covering imports, tool registration,
  `safe_code` attack rejection, `path_safety` traversal blocking, network
  idle detection, and the tools/ package wiring.
- `MECHCP_*` env-var table in README, TERMS_OF_USE.md, MIT license.

### Changed
- `debug_logger` rewritten: stderr-only (stdio-MCP safe), bounded
  `deque(maxlen)` per level, header redaction (`Authorization`, `Cookie`,
  `X-Api-Key`, etc.), pickle exports removed.
- `network_interceptor` request store bounded with `deque(maxlen=N)` and
  FIFO eviction; default filter for `Image/Font/Media/Stylesheet`.
- `wait_for_element` rewritten to push a single MutationObserver-backed
  promise instead of polling every 500ms.
- `dynamic_hook_system.Fetch.enable` is now lazy, deferred until the first
  hook is created. Eliminates both a per-request stall and the shutdown
  noise from in-flight RequestPaused handlers.
- `element_cloner` external fetches route through the tab's `fetch()` so
  the origin sees one JA3 and one cookie jar (previously Python `requests`
  produced a second, easily correlated fingerprint).
- JS templates cached at module load via `functools.lru_cache`.

### Removed
- `src/response_stage_hooks.py` (141 lines of dead code; never imported).
- Pickle and gzip-pickle export formats from the debug logger.
- The upstream `stealth-browser-mcp` README and demo media.

### Security
- All findings from the three-axis review (code/security/performance) were
  addressed before publication. See `docs/superpowers/plans/` for the
  detailed audit notes.

[Unreleased]: https://github.com/RsGoksel/MechCP/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/RsGoksel/MechCP/releases/tag/v0.3.0
