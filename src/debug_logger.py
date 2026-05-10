"""Centralized debug logging for the MCP server.

This logger is safe for stdio MCP transports: every textual side effect goes
to *stderr* — never stdout — because stdout is reserved for JSON-RPC framing.

Collections are capped to a configurable size so long-running browser sessions
cannot exhaust memory through unbounded log accumulation, and request data is
redacted before being persisted to keep cookies, authorization headers, and
API keys out of debug exports.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import traceback
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional

from path_safety import safe_join, sanitize_filename


_DEFAULT_MAX_ENTRIES = int(os.environ.get("MECHCP_LOG_MAX_ENTRIES", "2000"))
_REDACT_VALUE = "***REDACTED***"
_SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-csrf-token",
        "x-amz-security-token",
    }
)
_SENSITIVE_KEYS = frozenset({"password", "secret", "token", "api_key", "apikey", "auth"})


def _build_stderr_logger() -> logging.Logger:
    """Configure a singleton stderr-only logger for the package."""
    logger = logging.getLogger("mechcp")
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s][%(levelname)s][%(name)s] %(message)s")
    )
    logger.addHandler(handler)
    level_name = os.environ.get("MECHCP_LOG_LEVEL", "WARNING").upper()
    logger.setLevel(getattr(logging, level_name, logging.WARNING))
    logger.propagate = False
    return logger


_PY_LOGGER = _build_stderr_logger()


def redact_headers(headers: Optional[Mapping[str, str]]) -> Dict[str, str]:
    """Return a copy of `headers` with sensitive values redacted."""
    if not headers:
        return {}
    redacted: Dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in _SENSITIVE_HEADERS:
            redacted[key] = _REDACT_VALUE
        else:
            redacted[key] = value
    return redacted


def redact_mapping(payload: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Recursively redact obviously-sensitive keys in a structured payload."""
    if not payload:
        return {}
    out: Dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in _SENSITIVE_KEYS:
            out[key] = _REDACT_VALUE
        elif isinstance(value, Mapping):
            out[key] = redact_mapping(value)
        else:
            out[key] = value
    return out


class DebugLogger:
    """Thread-safe in-memory log buffer with capped collections."""

    def __init__(self, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._errors: Deque[Dict[str, Any]] = deque(maxlen=max_entries)
        self._warnings: Deque[Dict[str, Any]] = deque(maxlen=max_entries)
        self._info: Deque[Dict[str, Any]] = deque(maxlen=max_entries)
        self._stats: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._enabled = True
        self._seen_errors: Deque[str] = deque(maxlen=max_entries)
        self._seen_set: set[str] = set()

    def _record_error_signature(self, signature: str) -> bool:
        """Track unique error signatures with a bounded LRU."""
        if signature in self._seen_set:
            return False
        if len(self._seen_errors) == self._seen_errors.maxlen:
            evicted = self._seen_errors[0]
            self._seen_set.discard(evicted)
        self._seen_errors.append(signature)
        self._seen_set.add(signature)
        return True

    def log_error(
        self,
        component: str,
        method: str,
        error: BaseException | str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an error and emit it on stderr."""
        if not self._enabled:
            return

        if isinstance(error, BaseException):
            error_type = type(error).__name__
            error_message = str(error)
            tb = traceback.format_exc()
        else:
            error_type = "Error"
            error_message = str(error)
            tb = ""

        with self._lock:
            signature = f"{component}.{method}.{error_type}.{error_message}"
            self._stats[f"{component}.{method}.errors"] += 1
            if not self._record_error_signature(signature):
                return

            entry: Dict[str, Any] = {
                "timestamp": datetime.now().isoformat(),
                "component": component,
                "method": method,
                "error_type": error_type,
                "error_message": error_message,
                "traceback": tb,
                "context": redact_mapping(context),
            }
            self._errors.append(entry)

        _PY_LOGGER.error("%s.%s: %s", component, method, error_message)

    def log_warning(
        self,
        component: str,
        method: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a warning and emit it on stderr."""
        if not self._enabled:
            return
        with self._lock:
            self._warnings.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "component": component,
                    "method": method,
                    "message": message,
                    "context": redact_mapping(context),
                }
            )
            self._stats[f"{component}.{method}.warnings"] += 1
        _PY_LOGGER.warning("%s.%s: %s", component, method, message)

    def log_info(
        self,
        component: str,
        method: str,
        message: str,
        data: Optional[Any] = None,
    ) -> None:
        """Record an info message and emit it on stderr at DEBUG level."""
        if not self._enabled:
            return
        with self._lock:
            self._info.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "component": component,
                    "method": method,
                    "message": message,
                    "data": data if not isinstance(data, Mapping) else redact_mapping(data),
                }
            )
            self._stats[f"{component}.{method}.calls"] += 1
        _PY_LOGGER.debug("%s.%s: %s", component, method, message)

    def get_debug_view(self) -> Dict[str, Any]:
        """Backward-compatible default view (last 10 of each level)."""
        return self.get_debug_view_paginated()

    def get_debug_view_paginated(
        self,
        max_errors: Optional[int] = None,
        max_warnings: Optional[int] = None,
        max_info: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Snapshot the current log buffers."""
        with self._lock:
            errors = list(self._errors)
            warnings = list(self._warnings)
            info = list(self._info)
            stats = dict(self._stats)

        def _slice(items: List[Dict[str, Any]], limit: Optional[int]) -> List[Dict[str, Any]]:
            if limit is None:
                return items
            return items[-limit:] if limit > 0 else []

        limited_errors = _slice(errors, max_errors if max_errors is not None else 10)
        limited_warnings = _slice(warnings, max_warnings if max_warnings is not None else 10)
        limited_info = _slice(info, max_info if max_info is not None else 10)

        return {
            "summary": {
                "total_errors": len(errors),
                "total_warnings": len(warnings),
                "total_info": len(info),
                "returned_errors": len(limited_errors),
                "returned_warnings": len(limited_warnings),
                "returned_info": len(limited_info),
                "max_entries": self._max_entries,
                "error_types": self._error_summary(errors),
                "stats": stats,
            },
            "recent_errors": limited_errors,
            "recent_warnings": limited_warnings,
            "recent_info": limited_info,
            "all_errors": errors if max_errors is None else limited_errors,
            "all_warnings": warnings if max_warnings is None else limited_warnings,
            "all_info": info if max_info is None else limited_info,
            "component_breakdown": self._component_breakdown(errors, warnings, info),
        }

    @staticmethod
    def _error_summary(errors: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        types: Dict[str, int] = defaultdict(int)
        for e in errors:
            types[e["error_type"]] += 1
        return dict(types)

    @staticmethod
    def _component_breakdown(
        errors: Iterable[Dict[str, Any]],
        warnings: Iterable[Dict[str, Any]],
        info: Iterable[Dict[str, Any]],
    ) -> Dict[str, Dict[str, int]]:
        breakdown: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"errors": 0, "warnings": 0, "calls": 0}
        )
        for e in errors:
            breakdown[e["component"]]["errors"] += 1
        for w in warnings:
            breakdown[w["component"]]["warnings"] += 1
        for i in info:
            breakdown[i["component"]]["calls"] += 1
        return dict(breakdown)

    def clear_debug_view(self) -> None:
        """Drop every buffered log entry."""
        with self._lock:
            self._errors.clear()
            self._warnings.clear()
            self._info.clear()
            self._stats.clear()
            self._seen_errors.clear()
            self._seen_set.clear()
        _PY_LOGGER.info("debug logs cleared")

    # Compatibility alias kept for the old callsites.
    clear_debug_view_safe = clear_debug_view

    def enable(self) -> None:
        self._enabled = True
        _PY_LOGGER.info("debug logging enabled")

    def disable(self) -> None:
        self._enabled = False
        _PY_LOGGER.info("debug logging disabled")

    def get_lock_status(self) -> Dict[str, Any]:
        """Lightweight reflection used by the debug-status MCP tool."""
        return {
            "lock_acquired": self._lock.locked() if hasattr(self._lock, "locked") else False,
            "max_entries": self._max_entries,
            "buffered": {
                "errors": len(self._errors),
                "warnings": len(self._warnings),
                "info": len(self._info),
            },
        }

    def export_to_file(self, filepath: str = "debug_log.json") -> str:
        """Backward-compatible JSON export."""
        return self.export_to_file_paginated(filepath)

    def export_to_file_paginated(
        self,
        filepath: str = "debug_log.json",
        max_errors: Optional[int] = None,
        max_warnings: Optional[int] = None,
        max_info: Optional[int] = None,
        format: str = "json",
    ) -> str:
        """Export the current log buffers to a JSON file inside the sandbox.

        Pickle and gzip-pickle exports were removed because pickle deserialization
        is a code-execution surface — JSON is the only supported format now.
        """
        if format and format.lower() not in {"json", "auto"}:
            _PY_LOGGER.warning(
                "export format '%s' is no longer supported; falling back to JSON", format
            )

        safe_name = sanitize_filename(filepath, fallback="debug_log.json")
        if not safe_name.lower().endswith(".json"):
            safe_name = f"{safe_name}.json"
        target = safe_join(safe_name, allowed_suffixes={".json"})

        debug_data = self.get_debug_view_paginated(
            max_errors=max_errors,
            max_warnings=max_warnings,
            max_info=max_info,
        )
        with target.open("w", encoding="utf-8") as fh:
            json.dump(debug_data, fh, separators=(",", ":"), default=str)
        _PY_LOGGER.info(
            "exported %d errors / %d warnings / %d info entries to %s",
            debug_data["summary"]["returned_errors"],
            debug_data["summary"]["returned_warnings"],
            debug_data["summary"]["returned_info"],
            target,
        )
        return str(target)


debug_logger = DebugLogger()
