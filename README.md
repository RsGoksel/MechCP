# Stealth Browser MCP

**Supercharge your AI agent with undetectable, real-browser automation.**

Stealth Browser MCP provides powerful browser automation capabilities that bypass typical bot protections, allowing your AI to interact with websites naturally.

## Quickstart

### Recommended Setup

1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd stealth-browser-mcp
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Mac/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Add to Claude / MCP Client:**
   Configure your MCP client to run the server.

   **Windows Example:**
   ```json
   {
     "mcpServers": {
       "stealth-browser": {
         "command": "C:\\path\\to\\stealth-browser-mcp\\venv\\Scripts\\python.exe",
         "args": ["C:\\path\\to\\stealth-browser-mcp\\src\\server.py"],
         "env": {}
       }
     }
   }
   ```

   **Mac/Linux Example:**
   ```json
   {
     "mcpServers": {
       "stealth-browser": {
         "command": "/path/to/stealth-browser-mcp/venv/bin/python",
         "args": ["/path/to/stealth-browser-mcp/src/server.py"],
         "env": {}
       }
     }
   }
   ```

## Custom Installation Flags

You can customize the tools loaded by the server:
- `--minimal`: Loads only core browser automation and element interaction tools.
- `--disable-<section>`: Disables specific tool sections.
- `--list-sections`: Lists all available tool sections.

Example:
```bash
python src/server.py --minimal
```

## Operator Configuration (Environment Variables)

The server reads four environment variables. All are optional with sensible defaults; set them in the `env` block of your MCP client configuration when you need to deviate.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MECHCP_MAX_INSTANCES` | `5` | Maximum concurrent browser instances. Prevents runaway loops or prompt-injected agents from spawning unbounded Chrome processes. |
| `MECHCP_NETWORK_MAX_REQUESTS` | `5000` | Per-instance cap on captured network requests. Older entries are evicted FIFO. |
| `MECHCP_LOG_MAX_ENTRIES` | `2000` | Maximum number of buffered log entries per level (errors / warnings / info). |
| `MECHCP_LOG_LEVEL` | `WARNING` | Stderr log threshold (`DEBUG` / `INFO` / `WARNING` / `ERROR`). |
| `MECHCP_OUTPUT_DIR` | system temp + `/mechcp` | Allowlisted root for tools that write files to disk (screenshots, debug exports, element clones). Paths supplied by the AI agent are resolved into this directory; absolute paths and traversal segments are stripped. |
| `MECHCP_ALLOW_UNSAFE_CODE` | unset | Reserved future flag. Currently the AI-supplied Python paths (`create_dynamic_hook`, `create_python_binding`) always validate through `safe_code` regardless. |

## Security Notes

- The MCP server speaks JSON-RPC over **stdio**. All log output goes to stderr. Never run this server with stdout redirected to a TCP socket without isolating the JSON-RPC stream from log output.
- Chrome's CDP debug port is bound to `127.0.0.1` by default. If you containerize the server, do **not** expose that port; treat the container as a single-tenant trust boundary.
- AI-supplied Python in dynamic hooks is restricted by AST validation (no imports, no dunder access, no dangerous builtins). The validator is in `src/safe_code.py`; review it if you tighten or relax the policy.
- Sensitive request headers (`Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, etc.) are redacted before being written to debug logs and exports.

## Features

- **Undetectable Browser:** Bypasses basic bot protections.
- **CDP-Level Access:** Direct Chrome DevTools Protocol integration.
- **Element Interaction:** Natural clicking, typing, and scrolling.
- **Advanced Extraction:** Extract elements, styles, structure, and assets perfectly.
- **Network Debugging:** Intercept and monitor network traffic directly via AI chat.
- **Dynamic Hooks:** Write custom Python logic to intercept and modify requests in real-time.

## License

MIT License. See [LICENSE](LICENSE) for details.