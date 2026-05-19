# Contributing to MechCP

Thanks for your interest. MechCP is a hardened browser-automation MCP server for AI agents, and contributions are welcome.

## Development setup

1. Fork and clone:
   ```
   git clone https://github.com/<your-fork>/MechCP.git
   cd MechCP
   ```

2. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   source venv/bin/activate   # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   pip install pytest pytest-asyncio
   ```

3. Run the test suite to confirm the baseline is green:
   ```
   python -m pytest -v
   ```

4. Compile-check all source:
   ```
   python -m compileall -q src tests vendor
   ```

## Project conventions

- **Stdout is reserved for JSON-RPC.** Logs and banners go to stderr. Anything you add must respect this. When in doubt route through `debug_logger`.
- **AI-supplied Python paths must go through `safe_code.safe_compile`.** Do not call `exec`/`eval` directly on agent input.
- **File-write tools must resolve through `path_safety.safe_join`.** Caller-supplied paths are always treated as untrusted.
- **Pydantic v2 only.** Use `model_dump()` (not `.dict()`).
- **No bare `except:`.** Catch `Exception` and log with context.
- **Type hints encouraged.** `Optional[Any]` on a public MCP tool parameter is a smell because the LLM sees the JSON schema.

## Tests

- Smoke tests live in `tests/`. They do NOT spawn real browsers.
- Real-browser smoke is in `tests/manual_clone_smoke.py` (run manually).
- Every new MCP tool should have at least one test asserting its presence in the registry.
- Every new helper in `src/safe_code.py` or `src/path_safety.py` should have an attack-rejection test.

## Pull-request checklist

- [ ] `python -m pytest -v` passes locally.
- [ ] `python -m compileall -q src tests vendor` passes.
- [ ] No new `print()` calls hit stdout from within the MCP server runtime.
- [ ] Commit messages use conventional-commits prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- [ ] If you added a new MCP tool, the README "What it does" / tool list is updated.

## Reporting security issues

See `SECURITY.md` for the responsible-disclosure process. Do NOT open public issues for vulnerabilities.

## Code of conduct

Be excellent. Disagreements are fine; personal attacks, harassment, and bad-faith engagement are not, and will result in being blocked from the repo.
