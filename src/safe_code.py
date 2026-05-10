"""AST-based validation and sandboxed execution helpers.

This module hardens the surfaces where AI-supplied Python is compiled and
executed (the dynamic hook system and the JS-binding tool). The default policy
forbids imports, attribute access to dunder names, calls to dangerous builtins,
subprocess/os escape vectors, and walrus expressions that smuggle state into
otherwise-restricted scopes.

A compatibility layer keeps untrusted code blocked unless the operator
explicitly opts in by setting MECHCP_ALLOW_UNSAFE_CODE=1 in the environment.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional


_DANGEROUS_NAMES: FrozenSet[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "breakpoint",
        "__import__",
        "__builtins__",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "memoryview",
        "classmethod",
        "staticmethod",
        "type",
        "object",
        "super",
    }
)

_DANGEROUS_ATTRS: FrozenSet[str] = frozenset(
    {
        "__class__",
        "__bases__",
        "__base__",
        "__subclasses__",
        "__mro__",
        "__globals__",
        "__builtins__",
        "__getattribute__",
        "__getattr__",
        "__setattr__",
        "__delattr__",
        "__dict__",
        "__code__",
        "__closure__",
        "__import__",
        "__loader__",
        "__spec__",
        "__module__",
        "__init_subclass__",
        "__reduce__",
        "__reduce_ex__",
    }
)

_SAFE_BUILTINS: Dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
}


@dataclass
class ValidationResult:
    """Outcome of an AST validation pass."""

    valid: bool
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class _CodeValidator(ast.NodeVisitor):
    """AST walker that records dangerous constructs."""

    def __init__(self) -> None:
        self.issues: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802 (ast API)
        self.issues.append("import statements are not allowed")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        self.issues.append("from-import statements are not allowed")

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr in _DANGEROUS_ATTRS or node.attr.startswith("__"):
            self.issues.append(f"access to attribute '{node.attr}' is not allowed")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id in _DANGEROUS_NAMES:
            self.issues.append(f"reference to dangerous name '{node.id}'")

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Name) and node.func.id in _DANGEROUS_NAMES:
            self.issues.append(f"call to dangerous function '{node.func.id}'")
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:  # noqa: N802
        self.issues.append("global statements are not allowed")

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:  # noqa: N802
        self.issues.append("nonlocal statements are not allowed")

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # noqa: N802
        self.issues.append("walrus (named-expression) operator is not allowed")


def validate_code(
    code: str,
    *,
    require_function: Optional[str] = None,
    expected_arity: Optional[int] = None,
) -> ValidationResult:
    """Parse `code` and reject obvious sandbox-escape patterns.

    Args:
        code: Source string to validate.
        require_function: If set, the source must define a top-level function
            with this name.
        expected_arity: If set, the required function must take exactly this
            many positional arguments.

    Returns:
        ValidationResult with `valid=False` plus issues when unsafe constructs
        are present.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return ValidationResult(valid=False, issues=[f"syntax error: {exc.msg}"])

    visitor = _CodeValidator()
    visitor.visit(tree)
    issues = list(visitor.issues)
    warnings: List[str] = []

    if require_function:
        target = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == require_function
            ),
            None,
        )
        if target is None:
            issues.append(f"missing required function '{require_function}'")
        elif expected_arity is not None and len(target.args.args) != expected_arity:
            issues.append(
                f"function '{require_function}' must take exactly {expected_arity} parameter(s)"
            )

    return ValidationResult(valid=not issues, issues=issues, warnings=warnings)


def safe_builtins() -> Dict[str, Any]:
    """Return a fresh copy of the restricted builtins dict."""
    return dict(_SAFE_BUILTINS)


def safe_compile(
    code: str,
    *,
    filename: str = "<sandbox>",
    extra_globals: Optional[Dict[str, Any]] = None,
    require_function: Optional[str] = None,
    expected_arity: Optional[int] = None,
) -> Dict[str, Any]:
    """Validate, compile, and execute `code` in a restricted namespace.

    Returns the resulting namespace. Raises `PermissionError` when the code
    fails validation, and `SyntaxError` / `ValueError` when compile/exec fails.
    Module objects are deliberately *not* injected into the namespace because
    `module.__dict__` would re-expose unrestricted builtins.
    """
    result = validate_code(
        code, require_function=require_function, expected_arity=expected_arity
    )
    if not result.valid:
        raise PermissionError("; ".join(result.issues))

    namespace: Dict[str, Any] = {"__builtins__": safe_builtins()}
    if extra_globals:
        for key, value in extra_globals.items():
            if key == "__builtins__":
                continue
            namespace[key] = value

    compiled = compile(code, filename, "exec")
    exec(compiled, namespace)  # noqa: S102  # validated above
    return namespace


def is_unsafe_execution_allowed() -> bool:
    """Operator opt-in flag for code paths that compile AI-supplied Python."""
    return os.environ.get("MECHCP_ALLOW_UNSAFE_CODE", "").strip() in {"1", "true", "yes"}
