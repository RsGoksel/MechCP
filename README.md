# MechCP

A hardened Model Context Protocol (MCP) server that gives AI agents Chrome DevTools Protocol level browser control: navigation, DOM interaction, network interception, dynamic request hooks, and full element cloning.

MechCP is a fork of the upstream `stealth-browser-mcp` with a security and code-quality pass focused on running AI-supplied code safely on the host: AST-validated sandbox for dynamic hooks, sandboxed file output, redacted credential logging, bounded memory, and a 48-test smoke suite.

## What it does

- Spawns and manages real Chromium instances via `nodriver` (undetected by common anti-bot heuristics).
- Lets the agent navigate, click, type, scroll, capture screenshots, and read DOM structure.
- Intercepts network traffic, lets the agent write Python hook functions that block, redirect, or rewrite requests at runtime.
- Clones elements with their full styles, assets, and event listeners using CDP plus JS extraction.
- Speaks JSON-RPC over stdio so any MCP client (Claude Desktop, Cursor, Continue, etc.) can drive it.

## Quickstart

### 1. Clone

```bash
git clone https://github.com/RsGoksel/MechCP.git
cd MechCP
```

### 2. Create a virtual environment

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate
```

### 3. Install

```bash
pip install -r requirements.txt
```

The `py2js` dependency is vendored under `vendor/py2js/` so installation does not pull from a third-party fork.

### 4. Wire it into your MCP client

**Claude Desktop / Cursor (Windows):**

```json
{
  "mcpServers": {
    "mechcp": {
      "command": "C:\\path\\to\\MechCP\\venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\MechCP\\src\\server.py"],
      "env": {
        "MECHCP_MAX_INSTANCES": "3",
        "MECHCP_LOG_LEVEL": "WARNING"
      }
    }
  }
}
```

**Mac / Linux:**

```json
{
  "mcpServers": {
    "mechcp": {
      "command": "/path/to/MechCP/venv/bin/python",
      "args": ["/path/to/MechCP/src/server.py"],
      "env": {
        "MECHCP_MAX_INSTANCES": "3",
        "MECHCP_LOG_LEVEL": "WARNING"
      }
    }
  }
}
```

Restart your MCP client. The agent should now expose tools such as `spawn_browser`, `navigate`, `query_elements`, `click_element`, `take_screenshot`, `list_network_requests`, `create_dynamic_hook`, and the cloning toolset.

## Talking to the agent

Once the server is wired up, prompt your agent in plain English. A few examples that work out of the box:

- "Spawn a browser, go to example.com, click the More information link, and tell me what page you land on."
- "Open `https://news.ycombinator.com`, list the top 5 story titles and their points."
- "Visit `https://www.frontiersin.org/for-authors/home` and clone the main content section to a JSON file with all styles."
- "Add a network hook that blocks every request to `*.doubleclick.net` and reload `cnn.com` to confirm it worked."

## CLI flags

```bash
python src/server.py [flags]
```

- `--minimal` loads only browser management plus element interaction (skips network, hooks, cloning, etc.).
- `--disable-<section>` disables a specific section. Run `--list-sections` to see the names.
- `--transport http --host 127.0.0.1 --port 8000` runs on HTTP instead of stdio (development only).

## Operator configuration (environment variables)

All optional with sensible defaults. Set them in the `env` block of your MCP client config.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MECHCP_MAX_INSTANCES` | `5` | Maximum concurrent browser instances. Prevents runaway loops or prompt-injected agents from spawning unbounded Chrome processes. |
| `MECHCP_NETWORK_MAX_REQUESTS` | `5000` | Per-instance cap on captured network requests. Older entries are evicted FIFO. |
| `MECHCP_LOG_MAX_ENTRIES` | `2000` | Maximum buffered log entries per level (errors / warnings / info). |
| `MECHCP_LOG_LEVEL` | `WARNING` | Stderr log threshold (`DEBUG` / `INFO` / `WARNING` / `ERROR`). |
| `MECHCP_OUTPUT_DIR` | system temp + `/mechcp` | Allowlisted root for tools that write files (screenshots, debug exports, element clones). Paths supplied by the AI agent are resolved into this directory; absolute paths and traversal segments are stripped. |
| `MECHCP_DISABLED_SECTIONS` | unset | Comma-separated list of tool sections to disable at startup (e.g. `dynamic-hooks,cdp-functions`). Equivalent to passing `--disable-<section>` flags. |
| `MECHCP_ALLOW_UNSAFE_CODE` | `0` | When set to `1`, signals operator opt-in for paths that compile AI-supplied Python. The AST validator in `src/safe_code.py` always runs regardless; this flag exists so future relaxations require explicit consent. |

## Security model

- **Stdio safety.** The server speaks JSON-RPC over stdout. All log output is routed to stderr. Do not redirect stdout to anything other than the MCP client.
- **AI-supplied Python is sandboxed.** Every dynamic hook and Python binding goes through `src/safe_code.py`, an AST validator that blocks imports, dunder attribute access, walrus expressions, and dangerous builtins (`eval`, `exec`, `__import__`, `getattr`, `__builtins__`, etc.). Module objects are kept out of the exec namespace to close the standard sandbox-escape paths.
- **Path traversal is blocked.** Tools that take a path (`take_screenshot.file_path`, `export_debug_logs.filename`, the cloner's output directory) resolve the input through `src/path_safety.py` and refuse anything outside `MECHCP_OUTPUT_DIR`.
- **Credentials are redacted.** `Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, and similar headers are replaced with `***REDACTED***` before being written to log buffers or debug exports. Pickle exports were removed because pickle deserialization is itself an RCE surface.
- **Memory is bounded.** Network capture, debug logger, and hook stores all use `deque(maxlen=...)` with FIFO eviction. A long-running session cannot exhaust RAM through unbounded log accumulation.
- **CDP debug port stays local.** Chrome's debug port binds to `127.0.0.1`. If you containerize the server, do not expose that port. Treat the container as a single-tenant trust boundary.

## Tests

```bash
pip install pytest pytest-asyncio
python -m pytest -v
```

Expected: 48 tests pass (smoke imports, tool registration, cloner parity, tools/ package wiring, plus security tests for `safe_code` and `path_safety`).

## Acceptable use

See [TERMS_OF_USE.md](TERMS_OF_USE.md). Briefly: personal automation, defensive security with explicit authorization, and research are supported. Scraping in violation of a target site's terms of service, credential stuffing, or evading anti-fraud systems are not.

## License

MIT. See [LICENSE](LICENSE).
