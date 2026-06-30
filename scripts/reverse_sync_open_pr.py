#!/usr/bin/env python3
"""Open a draft reverse-sync PR in a provider repo for one inbound upstream PR.

Read-only against music-assistant/server (gh pr diff / view). All writes target
the provider repo only. Best-effort apply: always opens a draft PR; conflicts
are left in-tree and the PR is labelled needs-human.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _transform as t  # noqa: E402

UPSTREAM = "music-assistant/server"


def build_branch(domain: str, pr_number: int) -> str:
    return f"reverse-sync/{domain}-pr{pr_number}"


def build_pr_body(pr: dict, domain: str, conflicts: bool) -> str:
    lines = [
        f"Reverse-sync of upstream PR {pr['html_url']} into the `{domain}` provider.",
        "",
        f"Original author: @{pr['user']['login']} (credited via `Co-authored-by`).",
        "",
        "**Maintainer-owned files were NOT touched** — review `VERSION` and "
        "`translations/en.json` manually if the upstream change implies a bump.",
        "",
        "- [ ] Spec filled in (`specs/inprogress/`)",
        "- [ ] CHANGELOG entry finalized",
        "- [ ] Tests pass locally",
    ]
    if conflicts:
        lines.insert(
            1,
            "\n> ⚠ Patch applied with **conflicts** — `.rej`/markers left in the "
            "tree. Resolve them before marking ready.\n",
        )
    return "\n".join(lines)


def scaffold_paths(domain: str, pr_number: int) -> dict[str, str]:
    spec = f"specs/inprogress/reverse-sync-pr{pr_number}.md"
    return {
        spec: (
            f"# Reverse-sync: upstream PR #{pr_number}\n\n"
            "WIP=1\n\n"
            f"Ported from music-assistant/server#{pr_number} into `{domain}`.\n\n"
            "## Summary\n\n_TODO: describe the change._\n"
        ),
        "CHANGELOG.md": f"- Reverse-synced upstream PR #{pr_number} (WIP)\n",
    }


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, **kw)


def open_reverse_pr(
    domain: str,
    provider_path: str,
    provider_repo: str,
    default_branch: str,
    pr_number: int,
    provider_dir: str,
) -> dict:
    """Returns {'skipped': bool, 'reason'|'pr_url': str, 'conflicts': bool}."""
    pr_json = _run(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            UPSTREAM,
            "--json",
            "number,title,url,author",
        ],
        capture_output=True,
        check=True,
    ).stdout
    import json

    raw = json.loads(pr_json)
    pr = {
        "number": raw["number"],
        "title": raw["title"],
        "html_url": raw["url"],
        "user": {"login": raw["author"]["login"]},
    }

    patch = _run(
        ["gh", "pr", "diff", str(pr_number), "--repo", UPSTREAM, "--patch"],
        capture_output=True,
        check=True,
    ).stdout
    reversed_patch = t.reverse_diff(patch, domain, provider_path)
    if not reversed_patch.strip():
        return {"skipped": True, "reason": "no provider-path changes"}

    branch = build_branch(domain, pr_number)
    git = lambda *a: _run(["git", "-C", provider_dir, *a], capture_output=True)  # noqa: E731

    # Echo dedup: if the patch already applies as a no-op, skip.
    check = _run(
        ["git", "-C", provider_dir, "apply", "--check", "--reverse", "-"],
        input=reversed_patch,
        capture_output=True,
    )
    if check.returncode == 0:
        return {"skipped": True, "reason": "already present (no-op)"}

    git("checkout", default_branch)
    git("checkout", "-B", branch)

    apply_res = _run(
        ["git", "-C", provider_dir, "apply", "--3way", "-"],
        input=reversed_patch,
        capture_output=True,
    )
    conflicts = apply_res.returncode != 0

    for rel, content in scaffold_paths(domain, pr_number).items():
        dest = os.path.join(provider_dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        mode = "a" if rel.endswith("CHANGELOG.md") and os.path.exists(dest) else "w"
        with open(dest, mode) as fh:
            fh.write(content)

    git("add", "-A")
    author = pr["user"]["login"]
    trailer = f"Co-authored-by: {author} <{author}@users.noreply.github.com>"
    git("commit", "-m", f"reverse-sync: port {UPSTREAM}#{pr_number}\n\n{trailer}")
    git("push", "-u", "origin", branch, "--force-with-lease")

    labels = ["reverse-sync"] + (["needs-human"] if conflicts else [])
    create = _run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            provider_repo,
            "--base",
            default_branch,
            "--head",
            branch,
            "--draft",
            "--title",
            f"reverse-sync: {pr['title']} (#{pr_number})",
            "--body",
            build_pr_body(pr, domain, conflicts),
            *sum((["--label", x] for x in labels), []),
        ],
        capture_output=True,
    )
    return {
        "skipped": False,
        "pr_url": create.stdout.strip(),
        "conflicts": conflicts,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--provider-path", required=True)
    ap.add_argument("--provider-repo", required=True)
    ap.add_argument("--default-branch", required=True)
    ap.add_argument("--pr-number", type=int, required=True)
    ap.add_argument("--provider-dir", required=True)
    args = ap.parse_args()
    result = open_reverse_pr(
        args.domain,
        args.provider_path,
        args.provider_repo,
        args.default_branch,
        args.pr_number,
        args.provider_dir,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
