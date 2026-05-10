"""Path traversal protection for tools that accept caller-supplied paths.

Tools exposed over MCP receive arguments from an LLM. A misbehaving or
prompt-injected agent could ask the server to write to `/etc/`, `~/.ssh/`,
or other sensitive locations. The helpers here resolve every incoming path
to an absolute, real path and assert it descends from an allowlisted base
directory before any open/write call.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Iterable


def _default_base_dir() -> Path:
    """Read MECHCP_OUTPUT_DIR fresh on every call.

    The environment variable is consulted per-invocation rather than cached at
    import time so test fixtures (and operators who re-export the variable
    after startup) see their changes take effect immediately.
    """
    return Path(os.environ.get("MECHCP_OUTPUT_DIR", "")).expanduser()


# Backwards compatibility: some callers and tests imported the module-level
# constant directly. We expose it as a module attribute that always reflects
# the value at import time, but `_resolved_base` no longer relies on it.
DEFAULT_BASE_DIR = _default_base_dir()


def _resolved_base(base: Path | None) -> Path:
    """Return the canonical base directory, defaulting to a project sandbox."""
    if base is not None:
        target = Path(base).expanduser().resolve()
    else:
        configured = _default_base_dir()
        if configured != Path(""):
            target = configured.resolve()
        else:
            target = Path(tempfile.gettempdir()).resolve() / "mechcp"
    target.mkdir(parents=True, exist_ok=True)
    return target


_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._\-]")


def sanitize_filename(name: str, *, fallback: str = "output") -> str:
    """Strip path separators and dangerous characters from a bare filename."""
    if not name:
        return fallback
    base = os.path.basename(name)
    cleaned = _FILENAME_SAFE_RE.sub("_", base)
    cleaned = cleaned.strip(". ")
    return cleaned or fallback


def safe_join(
    relative_path: str,
    *,
    base: Path | None = None,
    create_parents: bool = True,
    allowed_suffixes: Iterable[str] | None = None,
) -> Path:
    """Resolve `relative_path` under `base` and reject traversal attempts.

    Args:
        relative_path: Caller-supplied path. Absolute paths are stripped to
            their basename so callers cannot escape the sandbox.
        base: Allowlisted root. Defaults to `$MECHCP_OUTPUT_DIR` or a temp
            sandbox.
        create_parents: Pre-create the parent directory structure.
        allowed_suffixes: If set, the final path must end with one of these
            extensions (case-insensitive).

    Returns:
        A `Path` that is guaranteed to live under the allowlisted base.

    Raises:
        ValueError: Path escapes the base directory or has a disallowed
            extension.
    """
    if not relative_path:
        raise ValueError("path must not be empty")

    base_dir = _resolved_base(base)
    # Treat POSIX-style leading slashes as absolute even on Windows, where
    # Path("/etc/shadow").is_absolute() returns False — without this, callers
    # could pass UNIX-style absolute paths and bypass the basename strip below.
    posix_absolute = relative_path.startswith(("/", "\\"))
    candidate = Path(relative_path)
    if candidate.is_absolute() or candidate.drive or posix_absolute:
        candidate = Path(candidate.name)

    parts = [sanitize_filename(part, fallback="_") for part in candidate.parts if part not in {"", ".", ".."}]
    if not parts:
        raise ValueError("path resolves to an empty value after sanitization")

    final = (base_dir / Path(*parts)).resolve()
    try:
        final.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(f"path escapes allowed base directory: {final}") from exc

    if allowed_suffixes:
        suffixes = {s.lower() for s in allowed_suffixes}
        if final.suffix.lower() not in suffixes:
            raise ValueError(
                f"path suffix '{final.suffix}' not in allowed suffixes {sorted(suffixes)}"
            )

    if create_parents:
        final.parent.mkdir(parents=True, exist_ok=True)

    return final
