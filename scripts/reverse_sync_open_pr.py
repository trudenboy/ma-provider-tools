#!/usr/bin/env python3
"""Open a draft reverse-sync PR in a provider repo for one inbound upstream PR.

Read-only against music-assistant/server (gh pr view + REST combined diff). All writes target
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

# Maintainer-owned files: never carried into a reverse PR (mirrors the
# forward-sync guard's ignore-list). The PR body promises these are untouched,
# so they must be stripped from the patch before it is applied.
MAINTAINER_OWNED_SUFFIXES = ("VERSION", "translations/en.json")


def _drop_maintainer_owned(patch_text: str) -> str:
    """Remove diff sections targeting maintainer-owned files (VERSION, en.json).

    The patch is already in provider-repo layout (post reverse_diff). Splits on
    ``diff --git`` and drops any section whose target path ends with a
    maintainer-owned suffix, so ``git apply`` can never modify those files.
    """
    sections: list[str] = []
    cur: list[str] = []
    for ln in patch_text.splitlines(keepends=True):
        if ln.startswith("diff --git "):
            if cur:
                sections.append("".join(cur))
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        sections.append("".join(cur))

    kept = []
    for sec in sections:
        header = sec.splitlines()[0] if sec else ""
        parts = header.split()
        target = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else ""
        if any(target.endswith(s) for s in MAINTAINER_OWNED_SUFFIXES):
            continue
        kept.append(sec)
    return "".join(kept)


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


def _fetch_pr_diff(pr_number: int) -> str:
    """Return the upstream PR's combined diff (read-only).

    Uses the REST diff media type rather than ``gh pr diff``: the latter emits
    a per-commit patch series, so a file touched by N commits appears as N
    separate ``diff --git`` sections.  Reverse-applying such interdependent
    same-file sections in forward order spuriously fails, which would defeat
    the echo no-op dedup below for multi-commit PRs (false "not present" ->
    duplicate/conflicting PR).  The API diff is a single combined section per
    file, so reverse_diff, the dedup probe, and ``git apply --3way`` all behave
    deterministically.
    """
    return _run(
        [
            "gh",
            "api",
            f"repos/{UPSTREAM}/pulls/{pr_number}",
            "-H",
            "Accept: application/vnd.github.diff",
        ],
        capture_output=True,
        check=True,
    ).stdout


def _git_mut(provider_dir: str, *args: str) -> subprocess.CompletedProcess:
    """Run a mutating git command; raise RuntimeError on non-zero exit."""
    result = _run(["git", "-C", provider_dir, *args], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result


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

    patch = _fetch_pr_diff(pr_number)
    reversed_patch = _drop_maintainer_owned(
        t.reverse_diff(patch, domain, provider_path)
    )
    if not reversed_patch.strip():
        return {"skipped": True, "reason": "no provider-path changes"}

    branch = build_branch(domain, pr_number)

    # Echo dedup: if the patch already applies as a no-op, skip.
    check = _run(
        ["git", "-C", provider_dir, "apply", "--check", "--reverse", "-"],
        input=reversed_patch,
        capture_output=True,
    )
    if check.returncode == 0:
        return {"skipped": True, "reason": "already present (no-op)"}

    # Set a committer identity on the clone: CI runners and shallow clones have
    # no user.name/user.email, so `git commit` would fail with rc=128
    # "Author identity unknown". The contributor is credited via the
    # Co-authored-by trailer; the committer is the bot.
    _git_mut(provider_dir, "config", "user.name", "github-actions[bot]")
    _git_mut(
        provider_dir,
        "config",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    )

    _git_mut(provider_dir, "checkout", default_branch)
    _git_mut(provider_dir, "checkout", "-B", branch)

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

    _git_mut(provider_dir, "add", "-A")
    author = pr["user"]["login"]
    trailer = f"Co-authored-by: {author} <{author}@users.noreply.github.com>"
    _git_mut(
        provider_dir,
        "commit",
        "-m",
        f"reverse-sync: port {UPSTREAM}#{pr_number}\n\n{trailer}",
    )
    _git_mut(provider_dir, "push", "-u", "origin", branch, "--force-with-lease")

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
    if create.returncode != 0:
        raise RuntimeError(
            f"gh pr create failed (rc={create.returncode}): {create.stderr.strip()}"
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
