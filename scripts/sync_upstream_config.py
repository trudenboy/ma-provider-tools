#!/usr/bin/env python3
"""Sync ruff/mypy/codespell config blocks from upstream music-assistant/server.

Fetches `pyproject.toml` from `music-assistant/server` (main branch by default)
and regenerates two wrapper templates so every provider repo lints and
type-checks with the exact rules the upstream project uses:

- `wrappers/ruff.toml.j2` — fully replaced by upstream `[tool.ruff]`.
- `wrappers/pyproject.toml.j2` — only the auto-synced blocks (delimited by
  `>>> ma-provider-tools sync (...) >>>` / `<<<` markers) are replaced;
  Jinja-templated values such as `python_version`, `packages`, the
  `[[tool.mypy.overrides]]` block, and `codespell.ignore-words-list`
  are preserved.

Usage:
    python3 scripts/sync_upstream_config.py
    python3 scripts/sync_upstream_config.py --check  # exit 1 on drift, no writes
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
WRAPPERS = REPO_ROOT / "wrappers"
RUFF_TEMPLATE = WRAPPERS / "ruff.toml.j2"
PYPROJECT_TEMPLATE = WRAPPERS / "pyproject.toml.j2"

UPSTREAM_URL = (
    "https://raw.githubusercontent.com/music-assistant/server/main/pyproject.toml"
)

RUFF_HEADER = (
    "# Auto-synced from music-assistant/server/pyproject.toml [tool.ruff].\n"
    "# Do not edit — `scripts/sync_upstream_config.py` regenerates this file weekly.\n"
)


def fetch_upstream(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read()
    return tomllib.loads(body.decode("utf-8"))


def _format_value(value: Any, indent: int = 0) -> str:
    """Format a Python value as TOML, with multi-line lists when long."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Use double-quoted TOML strings; escape backslashes and quotes.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        if not value:
            return "[]"
        # Single-line if short, multi-line otherwise.
        joined_inline = ", ".join(_format_value(v) for v in value)
        if len(joined_inline) <= 80 and "\n" not in joined_inline:
            return f"[{joined_inline}]"
        pad = "  " * (indent + 1)
        items = ",\n".join(f"{pad}{_format_value(v, indent + 1)}" for v in value)
        return "[\n" + items + ",\n" + ("  " * indent) + "]"
    raise TypeError(f"Unsupported TOML value type: {type(value).__name__}")


def render_ruff_toml(ruff_cfg: dict[str, Any]) -> str:
    """Render the upstream [tool.ruff] dict as a standalone ruff.toml file.

    Mirrors the upstream layout: top-level scalars, then [format], then
    [lint] and its nested tables.
    """
    out: list[str] = [RUFF_HEADER]

    # Top-level scalars (fix, show-fixes, line-length, target-version)
    top_keys = ["fix", "show-fixes", "line-length", "target-version"]
    for key in top_keys:
        if key in ruff_cfg:
            out.append(f"{key} = {_format_value(ruff_cfg[key])}")
    out.append("")

    if "format" in ruff_cfg:
        out.append("[format]")
        for key, value in ruff_cfg["format"].items():
            out.append(f"{key} = {_format_value(value)}")
        out.append("")

    if "lint" in ruff_cfg:
        lint = ruff_cfg["lint"]
        out.append("[lint]")
        # Order: select, ignore first (most-read), then nested tables.
        for key in ("select", "ignore"):
            if key in lint:
                out.append(f"{key} = {_format_value(lint[key])}")
        # Nested tables in a stable order matching the existing template.
        nested_order = [
            ("pydocstyle", "lint.pydocstyle"),
            ("pylint", "lint.pylint"),
            ("mccabe", "lint.mccabe"),
            ("flake8-pytest-style", "lint.flake8-pytest-style"),
            ("isort", "lint.isort"),
        ]
        for inner_key, header in nested_order:
            if inner_key in lint and isinstance(lint[inner_key], dict):
                out.append("")
                out.append(f"[{header}]")
                for sub_key, sub_value in lint[inner_key].items():
                    out.append(f"{sub_key} = {_format_value(sub_value)}")
        # Append any remaining nested keys we didn't account for, defensively.
        accounted = {"select", "ignore"} | {k for k, _ in nested_order}
        for inner_key, inner_value in lint.items():
            if inner_key in accounted:
                continue
            if isinstance(inner_value, dict):
                out.append("")
                out.append(f"[lint.{inner_key}]")
                for sub_key, sub_value in inner_value.items():
                    out.append(f"{sub_key} = {_format_value(sub_value)}")

    return "\n".join(out).rstrip() + "\n"


def render_mypy_block(mypy_cfg: dict[str, Any]) -> str:
    """Render upstream [tool.mypy] with provider overrides.

    Provider-specific overrides:
    - `python_version`: kept as Jinja expression so each provider can pin
      its own Python version via providers.yml.
    - `packages`: forced to ["tests", "provider"] (provider repo layout).
    - `exclude`: dropped — those paths are upstream-internal.

    The [[tool.mypy.overrides]] block lives outside the auto-synced
    region, so this function does not render it.
    """
    cfg = dict(mypy_cfg)
    cfg.pop("exclude", None)
    cfg["packages"] = ["tests", "provider"]

    lines = ["[tool.mypy]"]
    lines.append("python_version = \"{{ python_version | default('3.12') }}\"")
    cfg.pop("python_version", None)

    # Stable ordering: preserve upstream key order to minimize diff churn.
    for key, value in cfg.items():
        lines.append(f"{key} = {_format_value(value)}")

    return "\n".join(lines)


# Codespell `skip` patterns that exist only in provider repos and must be
# preserved alongside whatever upstream contributes.
PROVIDER_CODESPELL_SKIP_EXTRA: tuple[str, ...] = ("docs-site/package-lock.json",)


def render_codespell_skip_block(codespell_cfg: dict[str, Any]) -> str:
    """Render the auto-synced part of [tool.codespell] (the `skip` value).

    Strategy:
    - Take upstream patterns, drop those that reference upstream-only paths
      (`music_assistant/...`) — they cannot match anything in a provider repo.
    - Append provider-specific patterns that upstream doesn't know about.

    `ignore-words-list` is provider-specific and stays outside this block.
    """
    upstream_skip = codespell_cfg.get("skip", "")
    upstream_parts = [p.strip() for p in upstream_skip.split(",") if p.strip()]
    filtered = [p for p in upstream_parts if not p.startswith("music_assistant/")]
    extras = [p for p in PROVIDER_CODESPELL_SKIP_EXTRA if p not in filtered]
    merged = filtered + extras
    return f'skip = "{",".join(merged)}"'


_MARKER_PATTERNS = {
    "mypy": (
        "# >>> ma-provider-tools sync (mypy) — DO NOT EDIT >>>",
        "# <<< ma-provider-tools sync (mypy) <<<",
    ),
    "codespell_skip": (
        "# >>> ma-provider-tools sync (codespell skip) — DO NOT EDIT >>>",
        "# <<< ma-provider-tools sync (codespell skip) <<<",
    ),
}


def replace_block(content: str, block_id: str, new_body: str) -> str:
    """Replace the body between the named >>> / <<< markers."""
    begin, end = _MARKER_PATTERNS[block_id]
    pattern = re.compile(
        re.escape(begin) + r"\n.*?\n" + re.escape(end),
        flags=re.DOTALL,
    )
    replacement = f"{begin}\n{new_body}\n{end}"
    new_content, count = pattern.subn(replacement, content)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly 1 match for block {block_id!r}, got {count}"
        )
    return new_content


def sync(check_only: bool = False) -> int:
    upstream = fetch_upstream(UPSTREAM_URL)
    tool = upstream.get("tool", {})

    if not all(k in tool for k in ("ruff", "mypy", "codespell")):
        print(
            "ERROR: upstream pyproject.toml is missing one of [tool.ruff/mypy/codespell]",
            file=sys.stderr,
        )
        return 2

    new_ruff = render_ruff_toml(tool["ruff"])
    new_mypy_block = render_mypy_block(tool["mypy"])
    new_codespell_skip = render_codespell_skip_block(tool["codespell"])

    pyproject_text = PYPROJECT_TEMPLATE.read_text()
    new_pyproject = replace_block(pyproject_text, "mypy", new_mypy_block)
    new_pyproject = replace_block(new_pyproject, "codespell_skip", new_codespell_skip)

    current_ruff = RUFF_TEMPLATE.read_text() if RUFF_TEMPLATE.exists() else ""

    ruff_changed = current_ruff != new_ruff
    pyproject_changed = pyproject_text != new_pyproject

    if not ruff_changed and not pyproject_changed:
        print("In sync with upstream — no changes.")
        return 0

    if check_only:
        if ruff_changed:
            print(
                "DRIFT: wrappers/ruff.toml.j2 differs from upstream.", file=sys.stderr
            )
        if pyproject_changed:
            print(
                "DRIFT: wrappers/pyproject.toml.j2 mypy/codespell blocks differ from upstream.",
                file=sys.stderr,
            )
        return 1

    if ruff_changed:
        RUFF_TEMPLATE.write_text(new_ruff)
        print(f"Updated {RUFF_TEMPLATE.relative_to(REPO_ROOT)}")
    if pyproject_changed:
        PYPROJECT_TEMPLATE.write_text(new_pyproject)
        print(f"Updated {PYPROJECT_TEMPLATE.relative_to(REPO_ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if templates drift from upstream; do not write files",
    )
    args = parser.parse_args()
    return sync(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
