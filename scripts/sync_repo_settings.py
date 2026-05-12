#!/usr/bin/env python3
"""Sync `providers.yml` repo metadata to GitHub via `gh repo edit`.

For each provider entry (skipping `server_fork`):
- `--description` ← `github_description`
- `--homepage` ← `github_homepage` (default: `https://trudenboy.github.io/<repo-name>/`)
- `--add-topic <each>` for every entry in `github_topics`
- `--enable-discussions`, `--enable-issues`

Default mode is `--dry-run` — prints the planned `gh` invocations without
executing them. `--apply` performs the calls. `--domain <D>` limits to a
single provider.

Idempotency: `gh repo edit --add-topic` is a no-op for already-present
topics; description / homepage overwrite (acceptable — `providers.yml`
is the central source of truth). Topics never removed; maintainer's
manual additions are preserved.

Requires `gh` CLI and `GH_TOKEN` env var (PAT with `repo:admin` scope)
when `--apply` is set.

Usage:
    python3 scripts/sync_repo_settings.py
    python3 scripts/sync_repo_settings.py --apply
    python3 scripts/sync_repo_settings.py --apply --domain yandex_music
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
PROVIDERS_FILE = REPO_ROOT / "providers.yml"


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _run_gh(args: list[str], *, apply: bool) -> int:
    """Print or run a `gh` command. Returns its exit code (0 on dry-run)."""
    cmd = ["gh", *args]
    if not apply:
        print(f"  [dry-run] {' '.join(cmd)}")
        return 0
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        print(f"  ERROR: {' '.join(cmd)} → {stderr}", file=sys.stderr)
    else:
        out = result.stdout.strip()
        if out:
            print(f"  {out}")
    return result.returncode


def _sync_provider(provider: dict, *, apply: bool) -> tuple[int, int]:
    """Run all `gh repo edit` invocations for one provider.

    :returns: (planned_count, errors_count)
    """
    repo = provider["repo"]
    desc = provider.get("github_description")
    topics = provider.get("github_topics") or []
    repo_name = repo.split("/", 1)[1] if "/" in repo else repo
    homepage = provider.get(
        "github_homepage", f"https://trudenboy.github.io/{repo_name}/"
    )

    if not desc:
        print(f"  Skipping {repo}: no github_description")
        return 0, 0

    planned = 0
    errors = 0

    # One call covers description + homepage + flags.
    rc = _run_gh(
        [
            "repo",
            "edit",
            repo,
            "--description",
            desc,
            "--homepage",
            homepage,
            "--enable-issues",
            "--enable-discussions",
        ],
        apply=apply,
    )
    planned += 1
    if rc != 0:
        errors += 1

    # Topics: one --add-topic per topic. `gh repo edit` supports multiple
    # --add-topic flags in a single invocation.
    if topics:
        add_topic_args: list[str] = ["repo", "edit", repo]
        for t in topics:
            add_topic_args.extend(["--add-topic", t])
        rc = _run_gh(add_topic_args, apply=apply)
        planned += 1
        if rc != 0:
            errors += 1

    return planned, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute gh commands (default: dry-run, prints commands only).",
    )
    parser.add_argument(
        "--domain",
        help="Only sync the provider with this domain (default: all non-fork).",
    )
    args = parser.parse_args()

    if args.apply and not _gh_available():
        print("ERROR: gh CLI not found in PATH", file=sys.stderr)
        return 2

    if not PROVIDERS_FILE.is_file():
        print(f"ERROR: {PROVIDERS_FILE} not found", file=sys.stderr)
        return 2

    data = yaml.safe_load(PROVIDERS_FILE.read_text())
    providers = [
        p for p in data.get("providers", []) if p.get("provider_type") != "server_fork"
    ]
    if args.domain:
        providers = [p for p in providers if p["domain"] == args.domain]
        if not providers:
            print(f"ERROR: domain {args.domain!r} not found", file=sys.stderr)
            return 2

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"sync_repo_settings ({mode}) — {len(providers)} provider(s)\n")

    total_planned = 0
    total_errors = 0
    for p in providers:
        print(f"--- {p['domain']} ({p['repo']}) ---")
        planned, errors = _sync_provider(p, apply=args.apply)
        total_planned += planned
        total_errors += errors
        print()

    print(
        f"Summary: {total_planned} gh invocation(s) "
        f"{'executed' if args.apply else 'planned'}, {total_errors} error(s)"
    )
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
