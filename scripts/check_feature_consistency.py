#!/usr/bin/env python3
"""Cross-validate provider features declared in ma-provider-tools vs code.

For a single provider:
- Look up its entry in `providers.yml`.
- AST-parse `<repo>/<provider_path>__init__.py` and collect the contents
  of the module-level `SUPPORTED_FEATURES = {...}` set literal.
- For every `features[i].feature_id` declared in `providers.yml`, hard-fail
  if it is not present in `SUPPORTED_FEATURES`.
- For every `features[i].slug` declared without `feature_id`, emit a soft
  warning (P0 transition; in P1 this becomes an error).
- Soft test-discovery: warn when a slug has no `tests/test_*<slug-suffix>*.py`
  file.
- `provider_type == "server_fork"` is skipped (no provider surface).

Runs both locally (pre-commit-friendly) and via
`reusable-check-feature-consistency.yml` in each provider's CI.

Usage:
    python3 scripts/check_feature_consistency.py \\
        --providers-yml providers.yml \\
        --domain yandex_music \\
        --repo-path /path/to/ma-provider-yandex-music
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

import yaml


def _extract_supported_features(init_path: Path) -> tuple[set[str], str | None]:
    """Return (members, warning) for the SUPPORTED_FEATURES assignment.

    :param init_path: Provider's `provider/__init__.py` path.
    :returns: A tuple ``(members, warning)`` where ``members`` is the set
        of ``ProviderFeature.X`` attribute names found on the RHS of a
        top-level ``SUPPORTED_FEATURES = {...}`` assignment. ``warning``
        is non-``None`` when the assignment shape is unrecognised
        (dynamic construction, function call, etc.) — in that case
        ``members`` is empty and callers should skip strict checks.
    """
    if not init_path.is_file():
        return set(), f"{init_path} not found"

    tree = ast.parse(init_path.read_text(), filename=str(init_path))

    target: ast.expr | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "SUPPORTED_FEATURES":
                    target = node.value
                    break
        elif isinstance(node, ast.AnnAssign):
            tgt = node.target
            if isinstance(tgt, ast.Name) and tgt.id == "SUPPORTED_FEATURES":
                target = node.value
        if target is not None:
            break

    if target is None:
        return set(), "no top-level SUPPORTED_FEATURES assignment found"

    members: set[str] = set()

    def collect_from_set(node: ast.expr) -> bool:
        if isinstance(node, ast.Set):
            for elt in node.elts:
                if (
                    isinstance(elt, ast.Attribute)
                    and isinstance(elt.value, ast.Name)
                    and elt.value.id == "ProviderFeature"
                ):
                    members.add(elt.attr)
                else:
                    return False
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "set"
            and not node.args
            and not node.keywords
        ):
            return True
        return False

    if collect_from_set(target):
        return members, None

    return set(), (
        "SUPPORTED_FEATURES RHS is not a static set literal "
        f"(got {type(target).__name__}); strict cross-validation skipped"
    )


def _discover_tests(tests_dir: Path, slug_suffix: str) -> list[str]:
    if not tests_dir.is_dir():
        return []
    pattern = f"test_*{slug_suffix.replace('-', '_')}*.py"
    return [str(p.relative_to(tests_dir)) for p in tests_dir.rglob(pattern)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--providers-yml", required=True, type=Path)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--repo-path", required=True, type=Path)
    parser.add_argument(
        "--strict-slug",
        action="store_true",
        help="Promote 'slug without feature_id' warnings to errors (P1 mode).",
    )
    args = parser.parse_args()

    if not args.providers_yml.is_file():
        print(f"ERROR: {args.providers_yml} not found", file=sys.stderr)
        return 2

    data = yaml.safe_load(args.providers_yml.read_text())
    entry = next(
        (p for p in data.get("providers", []) if p.get("domain") == args.domain),
        None,
    )
    if entry is None:
        print(
            f"ERROR: domain {args.domain!r} not found in providers.yml", file=sys.stderr
        )
        return 2

    if entry.get("provider_type") == "server_fork":
        print(f"check-feature-consistency: skipped ({args.domain} is server_fork)")
        return 0

    provider_path = entry.get("provider_path", "provider/")
    init_path = args.repo_path / provider_path / "__init__.py"
    supported, ast_warning = _extract_supported_features(init_path)

    hard_errors: list[str] = []
    warnings: list[str] = []

    features = entry.get("features") or []
    for i, feature in enumerate(features):
        label = feature.get("label", "<no label>")
        slug = feature.get("slug")
        feature_id = feature.get("feature_id")

        if feature_id:
            if ast_warning:
                warnings.append(
                    f"features[{i}] ({label!r}): feature_id={feature_id!r} declared but "
                    f"SUPPORTED_FEATURES could not be parsed ({ast_warning}); skipped"
                )
            elif feature_id not in supported:
                hard_errors.append(
                    f"features[{i}] ({label!r}): feature_id={feature_id!r} declared in "
                    f"providers.yml but not in SUPPORTED_FEATURES "
                    f"(actual: {sorted(supported) or 'empty'})"
                )

        if slug and not feature_id:
            msg = (
                f"features[{i}] ({label!r}): slug={slug!r} has no feature_id "
                "(P0 transition — add explicit feature_id or accept slug as display-only)"
            )
            if args.strict_slug:
                hard_errors.append(msg)
            else:
                warnings.append(msg)

        if slug:
            suffix = slug.split("/", 1)[1] if "/" in slug else slug
            tests_dir = args.repo_path / provider_path / "tests"
            if not tests_dir.is_dir():
                tests_dir = args.repo_path / "tests"
            matches = _discover_tests(tests_dir, suffix)
            if not matches:
                warnings.append(
                    f"features[{i}] ({label!r}): no test file found matching "
                    f"'test_*{suffix.replace('-', '_')}*.py' under {tests_dir}"
                )

    for w in warnings:
        print(f"WARN: {w}")
    for err in hard_errors:
        print(f"ERROR: {err}", file=sys.stderr)

    if hard_errors:
        return 1

    n_features = len(features)
    n_slugged = sum(1 for f in features if f.get("slug"))
    n_typed = sum(1 for f in features if f.get("feature_id"))
    print(
        f"check-feature-consistency: {args.domain} OK "
        f"({n_features} features, {n_slugged} slugged, {n_typed} typed; "
        f"{len(supported)} ProviderFeature members in SUPPORTED_FEATURES)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
