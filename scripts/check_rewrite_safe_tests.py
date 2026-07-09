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

1. **Non-aliased ``import provider`` / ``import provider.X``** — the rewrite
   now translates the *import statement* (see issue #99), but the bare
   ``provider.`` / ``provider.X.`` **attribute access** these force in the body
   is NOT translated (it can't be, without clobbering the legitimate
   ``provider`` test fixture). So the usage stays unrewritten and breaks
   upstream. The **aliased** form ``import provider.X as alias`` IS safe — the
   import line is rewritten and the body uses ``alias`` — and is the recommended
   alternative, alongside ``from provider import X`` / ``from provider.X import Y``.

2. **Per-line ``# noqa: PLC0415`` on a ``from provider`` import** does not
   survive the boundary: the rewrite lengthens the line, ruff reflows it to the
   parenthesised form, and the trailing ``# noqa`` detaches — so PLC0415 fires
   upstream. Use a file-level ``# ruff: noqa: PLC0415`` instead.

3. **Unguarded filesystem references to the sibling ``provider/`` directory in
   test code** (e.g. ``Path(__file__).parent.parent / "provider"`` fed into
   ``spec_from_file_location`` for working-tree aliasing). The path exists in
   the provider repo but NOT in the upstream layout, where the synced tests
   live in ``tests/providers/<domain>/`` next to no ``provider/`` sibling —
   dereferencing it kills collection with ``FileNotFoundError``. Any name
   bound to such a path must be guarded with ``.is_dir()`` / ``.exists()`` /
   ``.is_file()`` so the logic no-ops upstream.

This guard runs inside the provider repo's working directory and scans
``provider/`` and ``tests/``. Exits 1 if any unsafe pattern is found.
"""

from __future__ import annotations

import ast
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

# Rule A — a NON-aliased ``import provider`` / ``import provider.sub`` statement.
# The aliased form (``import provider.sub as alias``) is intentionally NOT
# matched: the sync rewrite now translates the import line (issue #99) and the
# body uses the alias, so it is safe. Plain/dotted non-aliased imports force
# bare ``provider.`` attribute access in the body, which the rewrite cannot
# translate without clobbering the ``provider`` test fixture — so they stay
# broken upstream and are flagged.
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


_GUARD_ATTRS = frozenset({"exists", "is_dir", "is_file"})


def _mentions_provider_path(node: ast.AST) -> bool:
    """True when *node* combines ``__file__`` with a ``"provider"`` segment."""
    has_file = any(
        isinstance(n, ast.Name) and n.id == "__file__" for n in ast.walk(node)
    )
    has_provider = any(
        isinstance(n, ast.Constant) and n.value == "provider" for n in ast.walk(node)
    )
    return has_file and has_provider


def _provider_path_guard_issues(path: Path, text: str) -> list[str]:
    """Rule C: sibling-``provider/`` paths in tests must be existence-guarded."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    bound: dict[str, int] = {}
    guarded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _mentions_provider_path(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.setdefault(target.id, node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _GUARD_ATTRS
            and isinstance(node.func.value, ast.Name)
        ):
            guarded.add(node.func.value.id)
    return [
        f"{path}:{lineno}: `{name}` points at the sibling `provider/` directory, "
        "which does not exist in the upstream layout (synced tests live in "
        "`tests/providers/<domain>/`) — dereferencing it there kills collection "
        "with FileNotFoundError. Guard the logic with "
        f"`if {name}.is_dir(): ...` so it no-ops upstream."
        for name, lineno in sorted(bound.items(), key=lambda kv: kv[1])
        if name not in guarded
    ]


def _scan_file(path: Path, *, domain: str, line_length: int) -> list[str]:
    """Return a list of human-readable issue strings for one file."""
    issues: list[str] = []
    text = path.read_text(encoding="utf-8")
    # Rule C applies to test code only: it is what gets rsynced into
    # tests/providers/<domain>/ upstream (the repo-root conftest.py is not).
    if path.parts and path.parts[0] == "tests":
        issues.extend(_provider_path_guard_issues(path, text))
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _IMPORT_PROVIDER_RE.match(line):
            issues.append(
                f"{path}:{lineno}: non-aliased `import provider...` forces bare "
                "`provider.` attribute access in the body, which the upstream "
                "rewrite cannot translate (it would clobber the `provider` test "
                "fixture). Use `import provider.X as alias`, `from provider import "
                "X`, or `from provider.X import Y`.\n"
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
