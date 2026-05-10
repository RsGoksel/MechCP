"""safe_code rejects every known sandbox-escape pattern."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


ATTACKS = [
    "import os",
    "from os import system",
    "().__class__.__bases__[0].__subclasses__()",
    "x = HookAction.__class__",
    "exec('print(1)')",
    "eval('1+1')",
    "open('/etc/passwd')",
    "getattr(request, '__class__')",
    "x.__globals__",
    "request.__class__.__mro__",
    "__import__('os')",
    "(n := len(request))",
    "__builtins__['exec']('print(1)')",
    "x = __builtins__",
]


@pytest.mark.parametrize("source", ATTACKS)
def test_safe_code_rejects_dangerous_constructs(source):
    from safe_code import validate_code

    body = f"def process_request(request):\n    {source}\n    return None"
    result = validate_code(body, require_function="process_request", expected_arity=1)
    assert not result.valid, f"safe_code accepted attack: {source}"
    assert result.issues, "validator reported invalid but produced no issues"


def test_safe_code_accepts_well_formed_hook():
    from safe_code import validate_code

    body = (
        "def process_request(request):\n"
        "    if request['method'] == 'POST':\n"
        "        return {'action': 'block'}\n"
        "    return {'action': 'continue'}\n"
    )
    result = validate_code(body, require_function="process_request", expected_arity=1)
    assert result.valid, result.issues


def test_safe_compile_blocks_sandbox_escape_at_runtime():
    from safe_code import safe_compile

    with pytest.raises(PermissionError):
        safe_compile(
            "def process_request(request):\n"
            "    return ().__class__.__bases__[0].__subclasses__()\n",
            require_function="process_request",
            expected_arity=1,
        )
