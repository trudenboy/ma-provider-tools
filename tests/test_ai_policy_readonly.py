import ast
import re
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
REVERSE = [
    "reverse_sync_radar.py",
    "reverse_sync_notify.py",
    "reverse_sync_open_pr.py",
    "check_upstream_ahead.py",
]
WRITE_VERBS = ("create", "comment", "edit", "review", "merge", "close")
REST_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _render_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue) and isinstance(
            value.value, ast.Name
        ):
            parts.append("{" + value.value.id + "}")
        else:
            parts.append("{expression}")
    return "".join(parts)


def _assert_no_upstream_rest_writes(name: str, text: str) -> None:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        args = [_render_string(item) for item in node.elts]
        if "api" not in args:
            continue
        upstream = any(
            value is not None
            and value.startswith("repos/")
            and ("music-assistant/" in value or "{UPSTREAM}" in value)
            for value in args
        )
        if not upstream:
            continue
        explicit_methods = {
            args[index + 1].upper()
            for index, value in enumerate(args[:-1])
            if value in {"--method", "-X"} and args[index + 1] is not None
        }
        implicit_post = (
            any(
                value in {"-f", "--raw-field", "-F", "--field", "--input"}
                for value in args
            )
            and "GET" not in explicit_methods
        )
        assert not (explicit_methods & REST_WRITE_METHODS or implicit_post), (
            f"{name}: upstream REST write command: {args}"
        )


def test_policy_guard_detects_upstream_rest_write():
    bad_source = """
UPSTREAM = "music-assistant/server"
_run(["gh", "api", f"repos/{UPSTREAM}/issues", "--method", "POST"])
"""

    with pytest.raises(AssertionError, match="REST write"):
        _assert_no_upstream_rest_writes("bad.py", bad_source)


def test_no_writes_to_upstream():
    """No reverse-sync script may issue a write gh command bound to UPSTREAM."""
    for name in REVERSE:
        text = (SCRIPTS / name).read_text()
        _assert_no_upstream_rest_writes(name, text)
        # Any `gh pr/issue <write-verb>` must not appear next to the UPSTREAM repo.
        for m in re.finditer(r'"(pr|issue)",\s*"(\w+)"', text):
            verb = m.group(2)
            if verb in WRITE_VERBS:
                # ensure UPSTREAM constant not used as --repo for this call:
                window = text[m.start() : m.start() + 400]
                assert (
                    "UPSTREAM" not in window and "music-assistant/server" not in window
                ), f"{name}: write verb {verb!r} near an upstream-repo reference"
