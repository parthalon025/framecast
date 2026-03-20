"""Architectural fitness tests — machine-enforced conventions.

These tests prevent convention drift by statically analysing source files.
They do NOT import any production code; they operate on raw AST / text.

Conventions enforced:
  1. Import direction: modules never import from routes (web_upload, api)
  2. Exception logging: except blocks with return must also log (Lesson #7)
  3. Gunicorn single worker: workers = 1 (Lesson #1356)
  4. Write lock encapsulation: _write_lock only in db.py (Lesson #1335)
  5. JSX callback param safety: no .map(h =>, etc. (Lesson #13, esbuild)
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT = Path(__file__).resolve().parent.parent
_APP = _PROJECT / "app"
_MODULES = _APP / "modules"
_FRONTEND_SRC = _APP / "frontend" / "src"

_MODULE_FILES = sorted(
    p for p in _MODULES.glob("*.py") if p.name != "__init__.py"
)
_ROUTE_NAMES = {"web_upload", "api"}

# Files covered by the exception-logging rule (modules + sse.py)
_EXCEPTION_LOG_FILES = [*_MODULE_FILES, _APP / "sse.py"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse(path: Path) -> ast.Module:
    return ast.parse(_read(path), filename=str(path))


def _iter_except_handlers(tree: ast.Module):
    """Yield every ``ast.ExceptHandler`` node in *tree*."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            yield node


def _body_has_return(handler: ast.ExceptHandler) -> bool:
    """True if the handler body contains a ``return`` statement."""
    for node in ast.walk(handler):
        if isinstance(node, ast.Return):
            return True
    return False


def _body_has_log_call(handler: ast.ExceptHandler) -> bool:
    """True if the handler body contains a ``log.<level>(...)`` call."""
    for node in ast.walk(handler):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            if (
                isinstance(func.value, ast.Name)
                and func.value.id == "log"
                and func.attr
                in ("debug", "info", "warning", "error", "exception", "critical")
            ):
                return True
    return False


def _body_is_input_parse(handler: ast.ExceptHandler) -> bool:
    """Heuristic: True if this is a trivial input-validation except block.

    Pattern: ``except (ValueError, TypeError): return <const>``
    These are parser guards (e.g. ``int(user_input)``), not error-swallowing
    blocks. Excluding them avoids false positives.
    """
    # Must catch only ValueError / TypeError (common parse errors)
    parse_exceptions = {"ValueError", "TypeError", "ImportError"}
    caught = set()
    if handler.type is None:
        return False
    if isinstance(handler.type, ast.Name):
        caught.add(handler.type.id)
    elif isinstance(handler.type, ast.Tuple):
        for elt in handler.type.elts:
            if isinstance(elt, ast.Name):
                caught.add(elt.id)
    if not caught or not caught.issubset(parse_exceptions):
        return False

    # Body must be a single return with a simple constant or bare return
    stmts = [s for s in handler.body if not isinstance(s, ast.Pass)]
    if len(stmts) != 1:
        return False
    stmt = stmts[0]
    if isinstance(stmt, ast.Return):
        # bare return, return False, return None, return {}
        val = stmt.value
        if val is None:
            return True
        if isinstance(val, ast.Constant) and val.value in (False, None, 0, ""):
            return True
        if isinstance(val, ast.Dict) and not val.keys:
            return True
    return False


# ---------------------------------------------------------------------------
# Test 1 — Import direction: modules never import from routes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_path", _MODULE_FILES, ids=lambda p: p.name)
def test_modules_never_import_routes(module_path: Path):
    """Modules must not import from route files (web_upload, api)."""
    tree = _parse(module_path)
    violations = []
    for node in ast.walk(tree):
        # from web_upload import ... / from app.web_upload import ...
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if any(part in _ROUTE_NAMES for part in parts):
                violations.append(
                    f"  line {node.lineno}: from {node.module} import ..."
                )
        # import web_upload / import app.api
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if any(part in _ROUTE_NAMES for part in parts):
                    violations.append(
                        f"  line {node.lineno}: import {alias.name}"
                    )
    assert not violations, (
        f"{module_path.name} imports from route layer:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Test 2 — Exception logging: except + return => must also log
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source_path",
    _EXCEPTION_LOG_FILES,
    ids=lambda p: p.relative_to(_APP).as_posix(),
)
def test_except_return_has_logging(source_path: Path):
    """Every except block (in modules + sse.py) that returns must also log.

    Trivial input-parse guards (``except (ValueError, TypeError): return False``)
    are excluded — they are intentional silent returns, not error swallowing.
    """
    tree = _parse(source_path)
    violations = []
    for handler in _iter_except_handlers(tree):
        if not _body_has_return(handler):
            continue
        if _body_has_log_call(handler):
            continue
        if _body_is_input_parse(handler):
            continue
        violations.append(
            f"  line {handler.lineno}: except block returns without logging"
        )
    assert not violations, (
        f"{source_path.relative_to(_APP)} has except-return blocks without log calls "
        f"(Lesson #7):\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Test 3 — Gunicorn single worker
# ---------------------------------------------------------------------------

def test_gunicorn_single_worker():
    """gunicorn.conf.py must set workers = 1 (Lesson #1356).

    SSE, CEC control, and the stats buffer are process-singletons.
    Multiple workers would silently break real-time features.
    """
    gunicorn_conf = _APP / "gunicorn.conf.py"
    assert gunicorn_conf.exists(), "gunicorn.conf.py not found"

    tree = _parse(gunicorn_conf)
    workers_value = None
    for node in ast.walk(tree):
        # Look for top-level: workers = <int>
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "workers":
                    if isinstance(node.value, ast.Constant):
                        workers_value = node.value.value

    assert workers_value is not None, (
        "gunicorn.conf.py does not assign `workers` at module level"
    )
    assert workers_value == 1, (
        f"gunicorn.conf.py sets workers = {workers_value}, must be 1 "
        "(SSE/CEC/stats are process-singletons)"
    )


# ---------------------------------------------------------------------------
# Test 4 — Write lock encapsulation
# ---------------------------------------------------------------------------

def test_write_lock_only_in_db():
    """_write_lock must never be referenced outside db.py (Lesson #1335).

    Routes must use db.py's public API; direct lock access couples callers
    to the serialisation mechanism and invites deadlocks.
    Test files are excluded — they may need lock access for test setup.
    """
    violations = []
    for py_file in _APP.rglob("*.py"):
        if py_file.name == "db.py":
            continue
        # Skip __pycache__
        if "__pycache__" in py_file.parts:
            continue
        source = _read(py_file)
        for i, line in enumerate(source.splitlines(), start=1):
            if "_write_lock" in line:
                rel = py_file.relative_to(_APP)
                violations.append(f"  {rel}:{i}: {line.strip()}")
    assert not violations, (
        "_write_lock referenced outside db.py (Lesson #1335):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Test 5 — JSX callback param safety (esbuild `h` shadowing)
# ---------------------------------------------------------------------------

# Pattern: .map(h => ...), .filter(h => ...), etc.
# esbuild injects `const {h} = preact` — using `h` as a callback param
# shadows the JSX factory and causes silent render failures.
_JSX_H_SHADOW_RE = re.compile(
    r"\.\s*(?:map|filter|forEach|find|some|every|reduce|flatMap|sort)"
    r"\s*\(\s*h\s*=>"
)


def test_jsx_no_h_callback_param():
    """No JSX file may use `h` as a callback parameter (Lesson #13).

    esbuild's Preact JSX transform injects ``h`` as the createElement
    factory. Using ``h`` as a ``.map()`` / ``.filter()`` parameter shadows
    it, causing silent render crashes. Use descriptive names instead.
    """
    if not _FRONTEND_SRC.exists():
        pytest.skip("frontend source not found")

    violations = []
    for jsx_file in sorted(_FRONTEND_SRC.rglob("*.jsx")):
        source = _read(jsx_file)
        for i, line in enumerate(source.splitlines(), start=1):
            if _JSX_H_SHADOW_RE.search(line):
                rel = jsx_file.relative_to(_FRONTEND_SRC)
                violations.append(f"  {rel}:{i}: {line.strip()}")
    assert not violations, (
        "JSX files use `h` as callback param (esbuild shadows h, Lesson #13):\n"
        + "\n".join(violations)
    )
