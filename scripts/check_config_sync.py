#!/usr/bin/env python3
"""Compare a provider's lint/typing config against the rendered template.

Run inside the provider repo's working directory. Expects:
- `ruff.toml` and `pyproject.toml` in CWD (the provider's live files)
- `_expected/ruff.toml` and `_expected/pyproject.toml` (rendered by
  `scripts/render_for_provider.py`)

Comparison rules:
- `ruff.toml` must match exactly (it's fully auto-synced from upstream).
- In `pyproject.toml`, only `[tool.mypy]` (incl. `overrides`) and
  `[tool.codespell].skip` must match. The rest of the file is provider-
  specific (deps, version, build-system, etc.).

Exits with status 1 on drift.
"""

from __future__ import annotations

import difflib
import sys
import tomllib
from pathlib import Path


def _emit_error(message: str) -> None:
    # Emit as a plain message *and* a GitHub Actions error annotation.
    print(message, file=sys.stderr)
    first_line = message.splitlines()[0]
    print(f"::error::{first_line}", file=sys.stderr)


def _diff(expected: str, local: str, name: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            local.splitlines(),
            fromfile=f"expected/{name}",
            tofile=f"local/{name}",
            lineterm="",
        )
    )


def main() -> int:
    issues: list[str] = []

    local_ruff_path = Path("ruff.toml")
    expected_ruff_path = Path("_expected/ruff.toml")
    if not expected_ruff_path.is_file():
        _emit_error(
            "Expected file _expected/ruff.toml not found. "
            "Did render_for_provider.py run?"
        )
        return 2
    if not local_ruff_path.is_file():
        issues.append(
            "ruff.toml is missing from the provider repo. "
            "It must exist and match the auto-synced template."
        )
    else:
        local_ruff = local_ruff_path.read_text()
        expected_ruff = expected_ruff_path.read_text()
        if local_ruff != expected_ruff:
            issues.append(
                "ruff.toml drifts from the auto-synced template:\n"
                + _diff(expected_ruff, local_ruff, "ruff.toml")
            )

    expected_py_path = Path("_expected/pyproject.toml")
    local_py_path = Path("pyproject.toml")
    if not expected_py_path.is_file() or not local_py_path.is_file():
        if not local_py_path.is_file():
            issues.append("pyproject.toml is missing from the provider repo.")
        else:
            _emit_error(
                "Expected file _expected/pyproject.toml not found. "
                "Did render_for_provider.py run?"
            )
            return 2
    else:
        with expected_py_path.open("rb") as f:
            expected = tomllib.load(f)
        with local_py_path.open("rb") as f:
            local = tomllib.load(f)

        local_mypy = local.get("tool", {}).get("mypy", {})
        expected_mypy = expected.get("tool", {}).get("mypy", {})
        if local_mypy != expected_mypy:
            issues.append(
                "[tool.mypy] differs from the auto-synced template.\n"
                f"  expected: {expected_mypy}\n"
                f"  local:    {local_mypy}"
            )

        local_skip = local.get("tool", {}).get("codespell", {}).get("skip", "")
        expected_skip = expected.get("tool", {}).get("codespell", {}).get("skip", "")
        if local_skip != expected_skip:
            issues.append(
                "[tool.codespell].skip differs from the auto-synced template.\n"
                f"  expected: {expected_skip!r}\n"
                f"  local:    {local_skip!r}"
            )

    if issues:
        for issue in issues:
            _emit_error(issue)
        print(
            "\nThis check enforces that lint and typing rules in this provider "
            "repo stay aligned with upstream music-assistant/server. Local edits "
            "to ruff.toml / [tool.mypy] / [tool.codespell].skip are not allowed "
            "— the templated versions in trudenboy/ma-provider-tools are the "
            "single source of truth, and the next distribute run will restore "
            "them. Reset the affected file(s) and reopen the PR.",
            file=sys.stderr,
        )
        return 1

    print("Config in sync ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
