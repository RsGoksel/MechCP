# Vendored: py2js

- **Upstream:** https://github.com/am230/py2js
- **Commit:** 31a83c7c25a51ab0cc3255f484a2279d26278ec3
- **Vendored on:** 2026-05-10
- **Reason:** The upstream is a personal fork with no PyPI release. Pinning
  by SHA does not protect against a maintainer-controlled force-push, so
  we vendor the contents to lock them under our own version control.

## Audit Notes

Audit query: `(exec|eval|__import__|subprocess|os\.system|requests\.)`
applied with the `Grep` tool over `vendor/py2js/`.

- `exec` callsites: none observed.
- `eval` callsites: none observed.
- `__import__` callsites: none observed.
- `subprocess` usage: none observed.
- `os.system` usage: none observed.
- `requests`/network calls: none observed. py2js has no runtime network
  dependency.

Additional file-I/O sweep (`open\(|file\(|os\.`):

- `vendor/py2js/py2js/py2js.py:674` — `path.exists() and path.is_file()`
  inside `track_imports`. Benign filesystem stat to walk Python imports
  for the AST translator.
- `vendor/py2js/py2js/visitor.py:52` — `inspect.getsourcefile(...)` /
  `inspect.getsourcelines(...)`. Used only to render error messages when
  a visitor method returns `None`.
- `vendor/py2js/setup.py:3` — `open('README.rst', ...)` to read the long
  description at install time. Standard packaging boilerplate.
- `vendor/py2js/README.rst` — docstring `open(...)` examples, not
  executable code.

The package does AST-based source-to-source translation (Python -> JS).
It does **not** evaluate user code at runtime, nor does it spawn
subprocesses or open network connections. The two `open(...)` callsites
in `setup.py` and the docstrings in `README.rst` are install-time and
documentation respectively.

## Updating

To pull a new upstream version:

1. Clone upstream at the new commit.
2. Diff against `vendor/py2js/`, review every change.
3. Replace the contents of `vendor/py2js/` and update the SHA + audit
   notes above.
4. Run the full test suite, including the smoke tests in `tests/`.
