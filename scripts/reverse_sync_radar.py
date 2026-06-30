#!/usr/bin/env python3
"""Reverse-sync radar: detect inbound provider PRs and open reverse PRs.

Read-only against music-assistant/server. Two passes per provider:
  A) anchor — latest upstream SHA on the provider path (consumed by the guard)
  B) action — merged PRs touching the path -> reverse-PR opener

Iterates providers.yml. Persists progress to state/reverse-sync.json.

Cursor decision
---------------
The cursor ``pulls_cursor`` is advanced only up to the latest ``updated_at``
of PRs that were **fully resolved** (marked handled) AND whose ``updated_at``
is strictly before the earliest failed PR's ``updated_at``.  This guarantees
that a PR for which the opener raised ``RuntimeError`` is never silently
dropped: it will remain re-discoverable on the next radar run because both
``is_handled`` returns False (not in handled_prs) and its ``updated_at``
exceeds the cursor.  Resolved PRs with a later timestamp than the earliest
failure are likewise held back — they are deduplicated by ``is_handled`` on
re-evaluation, so the only cost is a redundant echo/non-touching check.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reverse_sync_notify  # noqa: E402
import reverse_sync_open_pr as opener  # noqa: E402
import reverse_sync_state as st  # noqa: E402

UPSTREAM = "music-assistant/server"
HUB_REPO = "trudenboy/ma-provider-tools"
ECHO_LOGINS = {"github-actions[bot]", "trudenboy", "trudenboy[bot]"}
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(REPO_ROOT, "state", "reverse-sync.json")
PROVIDERS_PATH = os.path.join(REPO_ROOT, "providers.yml")
MAX_PAGES = 10  # safety cap for _merged_prs pagination (~1 000 PRs)


def _gh(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], text=True, capture_output=True, check=True
    ).stdout


def is_echo(pr: dict, echo_logins: set[str]) -> bool:
    return pr.get("user", {}).get("login") in echo_logins


def touches_provider(files: list[str], domain: str) -> bool:
    src_root = f"music_assistant/providers/{domain}/"
    test_root = f"tests/providers/{domain}/"
    return any(f.startswith(src_root) or f.startswith(test_root) for f in files)


def _upstream_default_branch() -> str:
    """Return the default branch of the upstream repo, falling back to 'dev'."""
    try:
        result = _gh(["api", f"repos/{UPSTREAM}", "--jq", ".default_branch"]).strip()
    except Exception:
        return "dev"
    # Guard against empty / "null" output (e.g. jq emits nothing) — an invalid
    # ref here would silently turn the radar into a no-op, the exact failure
    # this lookup exists to prevent.
    return result if result and result != "null" else "dev"


def select_unhandled(
    prs: list[dict], data: dict, domain: str, cursor: str | None
) -> list[dict]:
    out = []
    for pr in prs:
        if st.is_handled(data, domain, pr["number"]):
            continue
        if cursor and pr["updated_at"] <= cursor:
            continue
        out.append(pr)
    return out


def _anchor(domain: str, default_branch: str) -> str | None:
    raw = _gh(
        [
            "api",
            f"repos/{UPSTREAM}/commits"
            f"?path=music_assistant/providers/{domain}&sha={default_branch}&per_page=1",
            "--jq",
            ".[0].sha // empty",
        ]
    ).strip()
    return raw or None


def _merged_prs(default_branch: str, cursor: str | None) -> list[dict]:
    """Return merged PRs from the upstream repo, paginating until the cursor.

    Fetches pages of up to 100 PRs (sorted by updated_at DESC) and stops as
    soon as an empty page is received, a PR with updated_at <= cursor is found
    on the current page, or MAX_PAGES pages have been scanned.  A stderr
    warning is emitted when MAX_PAGES is reached without hitting the cursor so
    truncation is never silent.
    """
    results: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        raw = _gh(
            [
                "api",
                f"repos/{UPSTREAM}/pulls?state=closed&base={default_branch}"
                f"&sort=updated&direction=desc&per_page=100&page={page}",
                "--jq",
                "[.[] | select(.merged_at != null) | "
                "{number, updated_at, user:{login:.user.login}}]",
            ]
        )
        page_prs: list[dict] = json.loads(raw)
        if not page_prs:
            break
        results.extend(page_prs)
        # Results are sorted DESC; once a PR at or before the cursor appears,
        # every subsequent PR is older — no need to fetch further pages.
        if cursor and any(pr["updated_at"] <= cursor for pr in page_prs):
            break
    else:
        print(
            f"WARNING: _merged_prs scanned {MAX_PAGES} pages without reaching "
            f"cursor {cursor!r}; some merged PRs may have been truncated.",
            file=sys.stderr,
        )
    return results


def _pr_files(number: int) -> list[str]:
    raw = _gh(
        [
            "api",
            f"repos/{UPSTREAM}/pulls/{number}/files?per_page=100",
            "--jq",
            "[.[].filename]",
        ]
    )
    return json.loads(raw)


def _clone_provider(repo: str, branch: str, dest: str) -> None:
    token = os.environ["FORK_SYNC_PAT"]
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    subprocess.run(
        ["git", "clone", "--depth", "50", "--branch", branch, url, dest],
        check=True,
        capture_output=True,
        text=True,
    )


def run() -> int:
    registry = yaml.safe_load(Path(PROVIDERS_PATH).read_text())
    data = st.load(STATE_PATH)

    default_branch_up = _upstream_default_branch()

    try:
        for prov in registry["providers"]:
            domain = prov["domain"]
            entry = st.entry(data, domain)

            # Per-provider upstream reads: a transient gh/network error for one
            # provider must not abort all remaining providers.  A stderr log is
            # sufficient — no incident issue for transient read errors.
            try:
                # Pass A — anchor
                anchor = _anchor(domain, default_branch_up)
                if anchor:
                    entry["last_synced_sha"] = anchor

                # Pass B — action
                merged = _merged_prs(default_branch_up, entry["pulls_cursor"])
            except subprocess.CalledProcessError as exc:
                print(
                    f"WARNING: {domain} upstream read failed, skipping provider: {exc}",
                    file=sys.stderr,
                )
                continue

            candidates = select_unhandled(merged, data, domain, entry["pulls_cursor"])

            # Collect resolved and failed updated_at values to compute safe cursor.
            resolved_ats: list[str] = []
            min_failed_at: str | None = None

            for pr in candidates:
                if is_echo(pr, ECHO_LOGINS):
                    st.mark_handled(data, domain, pr["number"])
                    resolved_ats.append(pr["updated_at"])
                    continue

                # Per-PR isolation: _pr_files, _clone_provider, and open_reverse_pr
                # can each raise subprocess.CalledProcessError or RuntimeError.
                # Any failure is caught here so one PR does not abort the others.
                try:
                    if not touches_provider(_pr_files(pr["number"]), domain):
                        st.mark_handled(data, domain, pr["number"])
                        resolved_ats.append(pr["updated_at"])
                        continue
                    with tempfile.TemporaryDirectory() as tmp:
                        pdir = os.path.join(tmp, "provider")
                        _clone_provider(prov["repo"], prov["default_branch"], pdir)
                        result = opener.open_reverse_pr(
                            domain=domain,
                            provider_path=prov["provider_path"],
                            provider_repo=prov["repo"],
                            default_branch=prov["default_branch"],
                            pr_number=pr["number"],
                            provider_dir=pdir,
                        )
                        print(f"{domain} PR#{pr['number']}: {result}")
                        st.mark_handled(data, domain, pr["number"])
                        resolved_ats.append(pr["updated_at"])
                except (RuntimeError, subprocess.CalledProcessError) as exc:
                    # One provider/PR failure must NOT abort the rest of the run.
                    print(
                        f"ERROR: {domain} PR#{pr['number']} opener failed: {exc}",
                        file=sys.stderr,
                    )
                    if min_failed_at is None or pr["updated_at"] < min_failed_at:
                        min_failed_at = pr["updated_at"]
                    title = f"reverse-sync failed — {domain} PR#{pr['number']}"
                    body = (
                        f"reverse_sync_radar failed to open reverse PR for "
                        f"`{domain}` upstream PR#{pr['number']}:\n\n"
                        f"```\n{exc}\n```"
                    )
                    reverse_sync_notify.upsert_issue(
                        HUB_REPO, "incident:reverse-sync", title, body
                    )

            # Advance cursor only up to resolved PRs that precede the earliest
            # failure.  This keeps failed PRs re-discoverable on the next run
            # (their updated_at will exceed the cursor and is_handled returns False).
            max_cursor = entry["pulls_cursor"]
            for at in resolved_ats:
                if min_failed_at is None or at < min_failed_at:
                    max_cursor = max(max_cursor or "", at)
            entry["pulls_cursor"] = max_cursor
    finally:
        st.save(STATE_PATH, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
