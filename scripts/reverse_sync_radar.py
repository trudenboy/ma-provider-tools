#!/usr/bin/env python3
"""Reverse-sync radar: detect inbound provider PRs and open reverse PRs.

Read-only against music-assistant/server. Two passes per provider:
  A) anchor — latest upstream SHA on the provider path (consumed by the guard)
  B) action — merged PRs touching the path -> reverse-PR opener

Scheduled mode iterates providers.yml. Targeted mode retries one validated
domain/merged-PR pair without consulting or changing the cursor. Both persist
the same backward-compatible state in state/reverse-sync.json.

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

import argparse
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
            "[.[] | .filename, (.previous_filename // empty)]",
        ]
    )
    return json.loads(raw)


def _upstream_pr(number: int) -> dict:
    raw = _gh(
        [
            "api",
            f"repos/{UPSTREAM}/pulls/{number}",
            "--jq",
            "{number, updated_at, merged_at, user:{login:.user.login}}",
        ]
    )
    pr = json.loads(raw)
    if not isinstance(pr, dict) or pr.get("number") != number:
        raise RuntimeError(f"upstream PR#{number} lookup returned an invalid response")
    return pr


def _clone_provider(repo: str, branch: str, dest: str) -> None:
    token = os.environ["FORK_SYNC_PAT"]
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    subprocess.run(
        ["git", "clone", "--depth", "50", "--branch", branch, url, dest],
        check=True,
        capture_output=True,
        text=True,
    )


def _failure_incident(domain: str, pr_number: int, exc: Exception) -> None:
    title = f"reverse-sync failed — {domain} PR#{pr_number}"
    body = (
        "reverse_sync_radar failed to open reverse PR for "
        f"`{domain}` upstream PR#{pr_number}:\n\n```\n{exc}\n```"
    )
    reverse_sync_notify.upsert_issue(HUB_REPO, "incident:reverse-sync", title, body)


def _label_failure_incident(domain: str, pr_number: int, result: dict) -> None:
    failures = result.get("label_failures") or []
    if not failures:
        return
    details = "\n".join(
        f"- `{failure['label']}`: `{failure['diagnostic']}`" for failure in failures
    )
    title = f"reverse-sync labels failed — {domain} PR#{pr_number}"
    body = (
        f"Provider PR: {result.get('pr_url') or '<missing URL>'}\n\n"
        f"Failed labels:\n{details}"
    )
    reverse_sync_notify.upsert_issue(HUB_REPO, "incident:reverse-sync", title, body)


def _validate_durable_result(provider_repo: str, result: object) -> dict:
    if not isinstance(result, dict):
        raise RuntimeError("opener returned a non-durable non-object result")
    if result.get("skipped") is True:
        return result
    expected_prefix = f"https://github.com/{provider_repo}/pull/"
    pr_url = result.get("pr_url")
    if (
        result.get("skipped") is False
        and isinstance(pr_url, str)
        and pr_url.startswith(expected_prefix)
    ):
        return result
    raise RuntimeError(
        "opener returned a non-durable outcome: expected skip or provider PR URL"
    )


def _process_candidate(prov: dict, pr: dict, data: dict) -> bool:
    """Process one candidate; return True only for a durable resolved outcome."""
    domain = prov["domain"]
    number = pr["number"]
    if is_echo(pr, ECHO_LOGINS):
        st.mark_handled(data, domain, number)
        return True
    try:
        if not touches_provider(_pr_files(number), domain):
            st.mark_handled(data, domain, number)
            return True
        with tempfile.TemporaryDirectory() as tmp:
            pdir = os.path.join(tmp, "provider")
            _clone_provider(prov["repo"], prov["default_branch"], pdir)
            result = _validate_durable_result(
                prov["repo"],
                opener.open_reverse_pr(
                    domain=domain,
                    provider_path=prov["provider_path"],
                    provider_repo=prov["repo"],
                    default_branch=prov["default_branch"],
                    pr_number=number,
                    provider_dir=pdir,
                ),
            )
        print(f"{domain} PR#{number}: {result}")
        _label_failure_incident(domain, number, result)
        st.mark_handled(data, domain, number)
        return True
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(
            f"ERROR: {domain} PR#{number} opener failed: {exc}",
            file=sys.stderr,
        )
        _failure_incident(domain, number, exc)
        return False


def _targeted_inputs(
    registry: dict, retry_domain: str | None, retry_pr: int | str | None
) -> tuple[dict, dict] | None:
    domain = retry_domain or None
    raw_pr = retry_pr if retry_pr not in (None, "") else None
    if (domain is None) != (raw_pr is None):
        raise ValueError("retry_domain and retry_pr must be provided together")
    if domain is None:
        return None
    providers = [prov for prov in registry["providers"] if prov["domain"] == domain]
    if len(providers) != 1:
        raise ValueError(f"unknown retry_domain: {domain}")
    try:
        number = int(raw_pr)
    except (TypeError, ValueError) as exc:
        raise ValueError("retry_pr must be a positive PR number") from exc
    if number <= 0:
        raise ValueError("retry_pr must be a positive PR number")
    pr = _upstream_pr(number)
    if not pr.get("merged_at"):
        raise ValueError(f"upstream PR#{number} is not merged")
    return providers[0], pr


def run(retry_domain: str | None = None, retry_pr: int | str | None = None) -> int:
    registry = yaml.safe_load(Path(PROVIDERS_PATH).read_text())
    targeted = _targeted_inputs(registry, retry_domain, retry_pr)

    # Targeted input validation and the upstream merged check intentionally
    # happen before state is read: malformed dispatches cannot mutate state.
    data = st.load(STATE_PATH)
    try:
        if targeted is not None:
            prov, pr = targeted
            return 0 if _process_candidate(prov, pr, data) else 1

        default_branch_up = _upstream_default_branch()
        for prov in registry["providers"]:
            domain = prov["domain"]
            entry = st.entry(data, domain)

            try:
                anchor = _anchor(domain, default_branch_up)
                if anchor:
                    entry["last_synced_sha"] = anchor
                merged = _merged_prs(default_branch_up, entry["pulls_cursor"])
            except subprocess.CalledProcessError as exc:
                print(
                    f"WARNING: {domain} upstream read failed, skipping provider: {exc}",
                    file=sys.stderr,
                )
                continue

            candidates = select_unhandled(merged, data, domain, entry["pulls_cursor"])
            resolved_ats: list[str] = []
            min_failed_at: str | None = None
            for pr in candidates:
                if _process_candidate(prov, pr, data):
                    resolved_ats.append(pr["updated_at"])
                elif min_failed_at is None or pr["updated_at"] < min_failed_at:
                    min_failed_at = pr["updated_at"]

            max_cursor = entry["pulls_cursor"]
            for at in resolved_ats:
                if min_failed_at is None or at < min_failed_at:
                    max_cursor = max(max_cursor or "", at)
            entry["pulls_cursor"] = max_cursor
        return 0
    finally:
        st.save(STATE_PATH, data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retry-domain")
    parser.add_argument("--retry-pr")
    args = parser.parse_args()
    try:
        return run(args.retry_domain, args.retry_pr)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
