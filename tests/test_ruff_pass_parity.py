"""Parity guard for the upstream ruff fix/format pass.

The pass that makes a synced provider tree lint-clean against upstream
``music-assistant/server`` dev (D213, RUF012, ...) exists in two places:
``wrappers/upstream-pr.yml.j2`` (the canonical origin) and the ``upstream/*``
branch of the format step in ``reusable-sync-to-fork.yml``. If they drift, the
two sync paths produce differently-formatted trees and the upstream PR flips
between lint-green and lint-red depending on which workflow pushed last.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FILES = [
    REPO / ".github/workflows/reusable-sync-to-fork.yml",
    REPO / "wrappers/upstream-pr.yml.j2",
]

# The canonical lines of the pass. Both files must contain each of them
# verbatim (ignoring indentation): the pin extraction from upstream's
# pyproject.toml, the full autofix (``--unsafe-fixes`` covers the D213 /
# RUF012 class of fixes), and the translations/en.json regeneration that keeps
# upstream's build_translations_source pre-commit hook diff-free.
CANON_LINES = [
    r"RUFF_REQ=$(grep -oE 'ruff==[0-9]+\.[0-9]+\.[0-9]+' pyproject.toml | head -1)",
    "ruff check --fix --unsafe-fixes $RUFF_TARGETS || true",
    "ruff format $RUFF_TARGETS",
    "if [ -f scripts/build_translations.py ]; then",
    "|| python3 -m pip install --quiet orjson 2>/dev/null || true",
    "python3 -m scripts.build_translations \\",
    "|| python3 scripts/build_translations.py || true",
]


def test_ruff_pass_lines_present_in_both() -> None:
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        for line in CANON_LINES:
            assert line in text, f"{path.name} is missing the canonical line: {line}"


def test_sync_to_fork_gates_fix_pass_on_upstream_branches() -> None:
    """The full autofix must only run for upstream/* targets.

    integration/dev keeps the plain format-only pass (with the ruff<0.15
    formatter pin), so the fix pass has to sit behind the target_branch gate.
    """
    text = (REPO / ".github/workflows/reusable-sync-to-fork.yml").read_text(
        encoding="utf-8"
    )
    gate = text.index('if [[ "${{ inputs.target_branch }}" == upstream/* ]]')
    fix = text.index("ruff check --fix --unsafe-fixes")
    fallback = text.index("pip install --quiet 'ruff<0.15'")
    assert gate < fix < fallback, (
        "fix pass must be inside the upstream/* gate, before the fallback"
    )
