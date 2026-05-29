#!/usr/bin/env python3
"""Fail a provider's CI early if its Python uses upstream-rewrite-unsafe patterns.

When a provider is synced into ``music-assistant/server`` (and the
``trudenboy/ma-server`` fork), ``upstream-pr.yml`` / ``reusable-sync-to-fork.yml``
rewrite the local package root with ``sed``:

    provider.X  ->  music_assistant.providers.<domain>.X

That text rewrite is deliberately conservative — it only touches
``from provider.`` / ``from provider import`` / ``"provider.`` forms — because
the package name ``provider`` collides with the legitimate ``provider`` *fixture
variable* used in tests. Two patterns therefore pass in the provider repo but
break at the upstream boundary, where they surface as confusing red CI on a
PR nobody can edit directly:

1. **Non-aliased ``import provider[.X]``** forces bare ``provider.X`` attribute
   access, which the rewrite cannot translate without also clobbering the
   fixture variable — so the usage stays unrewritten and raises ``NameError``
   upstream. Use ``from provider import X`` or ``import provider.X as alias``.

2. **Per-line ``# noqa: PLC0415`` on a ``from provider`` import** does not
   survive the boundary: the rewrite lengthens the line, ruff reflows it to the
   parenthesised form, and the trailing ``# noqa`` detaches — so PLC0415 fires
   upstream. Use a file-level ``# ruff: noqa: PLC0415`` instead.

This guard runs inside the provider repo's working directory and scans
``provider/`` and ``tests/``. Exits 1 if any unsafe pattern is found.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

# Roots scanned, relative to CWD. Missing roots are skipped.
SCAN_ROOTS = ("provider", "tests")

# Fallback line length if ``ruff.toml`` has no explicit ``line-length`` (ruff's
# own default is 88; the MA-synced template uses 100).
_DEFAULT_LINE_LENGTH = 100

# Rule A — a non-aliased ``import provider`` / ``import provider.sub`` statement.
# Aliased forms (``import provider.sub as alias``) and ``from provider ...`` are
# intentionally NOT matched: they don't force bare ``provider.`` attribute access.
_IMPORT_PROVIDER_RE = re.compile(r"^\s*import\s+provider(?:\.[\w.]+)?\s*(?:#.*)?$")

# Rule B — a ``from provider[.sub] import ...`` line carrying a per-line noqa
# that suppresses PLC0415. Only a problem when the *rewritten* line exceeds the
# line length: ruff then reflows it and the trailing noqa detaches. Short
# imports stay single-line and keep their noqa, so they are left alone.
_FROM_PROVIDER_NOQA_RE = re.compile(
    r"^\s*from\s+provider(?:\.[\w.]+)?\s+import\b.*#\s*noqa:[^\n]*\bPLC0415\b"
)


def _read_line_length() -> int:
    ruff_path = Path("ruff.toml")
    if ruff_path.is_file():
        try:
            data = tomllib.loads(ruff_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            return _DEFAULT_LINE_LENGTH
        value = data.get("line-length")
        if isinstance(value, int):
            return value
    return _DEFAULT_LINE_LENGTH


def _read_domain() -> str | None:
    for candidate in (Path("provider/manifest.json"), Path("manifest.json")):
        if candidate.is_file():
            try:
                domain = json.loads(candidate.read_text(encoding="utf-8")).get("domain")
            except (json.JSONDecodeError, OSError):
                return None
            if isinstance(domain, str) and domain:
                return domain
    return None


def _rewrite(line: str, domain: str) -> str:
    """Mirror the ``sed`` rewrites the upstream-sync workflows apply to imports."""
    base = f"music_assistant.providers.{domain}"
    return line.replace("from provider.", f"from {base}.").replace(
        "from provider import", f"from {base} import"
    )


def _emit_error(message: str) -> None:
    # Emit as a plain message *and* a GitHub Actions error annotation.
    print(message, file=sys.stderr)
    first_line = message.splitlines()[0]
    print(f"::error::{first_line}", file=sys.stderr)


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _scan_file(path: Path, *, domain: str, line_length: int) -> list[str]:
    """Return a list of human-readable issue strings for one file."""
    issues: list[str] = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _IMPORT_PROVIDER_RE.match(line):
            issues.append(
                f"{path}:{lineno}: non-aliased `import provider...` — the upstream "
                "import-path rewrite cannot translate the bare `provider.` usage "
                "this enables (it collides with the `provider` fixture variable). "
                "Use `from provider import X` or `import provider.X as alias`.\n"
                f"    {line.strip()}"
            )
        elif _FROM_PROVIDER_NOQA_RE.match(line):
            rewritten_len = len(_rewrite(line, domain))
            if rewritten_len > line_length:
                issues.append(
                    f"{path}:{lineno}: per-line `# noqa: PLC0415` on a `from provider` "
                    f"import that rewrites to {rewritten_len} cols (> {line_length}) "
                    "upstream — ruff reflows the over-length line and the trailing "
                    "noqa detaches, so PLC0415 fires there. Use a file-level "
                    "`# ruff: noqa: PLC0415` instead.\n"
                    f"    {line.strip()}"
                )
    return issues


def main() -> int:
    domain = _read_domain()
    if domain is None:
        _emit_error(
            "Could not read `domain` from provider/manifest.json (or manifest.json). "
            "This guard must run inside a provider repo's working directory."
        )
        return 2
    line_length = _read_line_length()

    issues: list[str] = []
    for root_name in SCAN_ROOTS:
        root = Path(root_name)
        if not root.is_dir():
            continue
        for path in _iter_python_files(root):
            issues.extend(_scan_file(path, domain=domain, line_length=line_length))

    if issues:
        _emit_error(
            f"Found {len(issues)} upstream-rewrite-unsafe pattern(s) in provider "
            "Python. These pass here but break CI on the inlined upstream PR:\n\n"
            + "\n\n".join(issues)
        )
        return 1

    print("OK: no upstream-rewrite-unsafe import patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
