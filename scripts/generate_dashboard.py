#!/usr/bin/env python3
"""Generate docs/dashboard.md with live stats for all providers.

Fetches data from GitHub API via `gh api` for each provider defined in
providers.yml, then writes a Markdown dashboard page for MkDocs.

Usage:
    python3 scripts/generate_dashboard.py

Requires:
    - gh CLI installed and authenticated (or GH_TOKEN env var)
    - PyYAML installed
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
PROVIDERS_FILE = REPO_ROOT / "providers.yml"
OUTPUT_FILE = REPO_ROOT / "docs" / "dashboard.md"

# Providers skipped in CI status check (no test.yml)
CI_SKIP_WORKFLOW = {"server_fork"}


def gh_api(path: str, repo: str | None = None) -> object:
    """Call `gh api` and return parsed JSON. Returns None on error."""
    cmd = ["gh", "api", path, "--paginate", "-q", "."]
    env = {**os.environ}
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, env=env, timeout=30
        )
        # gh --paginate outputs multiple JSON objects; wrap in array if needed
        text = result.stdout.strip()
        if not text:
            return None
        # Try parsing as-is first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Paginated responses: multiple JSON arrays concatenated
            lines = [line for line in text.splitlines() if line.strip()]
            merged = []
            for line in lines:
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, list):
                        merged.extend(parsed)
                    else:
                        merged.append(parsed)
                except json.JSONDecodeError:
                    pass
            return merged if merged else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def gh_api_single(path: str, retries: int = 3, retry_delay: float = 5.0) -> object:
    """Call `gh api` without pagination (single object response).

    Retries on HTTP 202 (GitHub is computing the stat asynchronously).
    """
    import time

    cmd = ["gh", "api", path]
    for attempt in range(retries):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=30
            )
            if result.returncode != 0:
                # 202 Accepted: GitHub is computing stats, retry
                if "202" in result.stderr or not result.stdout.strip():
                    if attempt < retries - 1:
                        time.sleep(retry_delay)
                        continue
                return None
            return json.loads(result.stdout) if result.stdout.strip() else None
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return None
    return None


def count_list(data: object) -> int:
    """Return length of list, or 0 if not a list."""
    return len(data) if isinstance(data, list) else 0


def ci_emoji(conclusion: str | None) -> str:
    mapping = {
        "success": "✅",
        "failure": "❌",
        "cancelled": "⚫",
        "skipped": "⏭️",
        "timed_out": "⏱️",
        "action_required": "⚠️",
        "neutral": "⚪",
        "in_progress": "🔄",
        "queued": "🕐",
        None: "❓",
    }
    return mapping.get(conclusion or "", "❓")


def format_date(iso: str | None, relative: bool = True) -> str:
    """Format ISO timestamp to relative or short date."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if relative:
            now = datetime.now(timezone.utc)
            delta = now - dt
            days = delta.days
            if days == 0:
                hours = delta.seconds // 3600
                return f"{hours}h ago" if hours > 0 else "just now"
            if days < 30:
                return f"{days}d ago"
            if days < 365:
                months = days // 30
                return f"{months}mo ago"
            years = days // 365
            return f"{years}y ago"
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return "—"


def get_provider_stats(repo: str, provider_type: str) -> dict:
    """Fetch all stats for a single provider repo."""
    stats: dict = {}
    since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    # --- PRs ---
    pulls_open = gh_api(f"/repos/{repo}/pulls?state=open&per_page=100")
    pulls_list = pulls_open if isinstance(pulls_open, list) else []
    stats["pr_open"] = len(pulls_list)
    stats["pr_draft"] = sum(1 for p in pulls_list if p.get("draft"))

    pulls_closed = gh_api(f"/repos/{repo}/pulls?state=closed&per_page=100")
    closed_list = pulls_closed if isinstance(pulls_closed, list) else []
    stats["pr_merged_30d"] = sum(
        1 for p in closed_list if p.get("merged_at") and p["merged_at"] >= since_30d
    )

    # --- Issues (GitHub issues API excludes PRs via is_pr filter not available;
    #     but /issues?state=open returns both issues and PRs, so we filter) ---
    issues_open = gh_api(f"/repos/{repo}/issues?state=open&per_page=100")
    issues_list = [
        i
        for i in (issues_open if isinstance(issues_open, list) else [])
        if "pull_request" not in i
    ]
    stats["issues_open"] = len(issues_list)

    label_counts = {}
    for issue in issues_list:
        for label in issue.get("labels", []):
            name = label.get("name", "")
            label_counts[name] = label_counts.get(name, 0) + 1
    stats["bugs"] = label_counts.get("type:bug", 0)
    stats["enhancements"] = label_counts.get("type:enhancement", 0)
    stats["incidents"] = label_counts.get("incident:ci", 0)

    # --- CI status (test.yml, latest run) ---
    if provider_type not in CI_SKIP_WORKFLOW:
        ci_data = gh_api_single(
            f"/repos/{repo}/actions/workflows/test.yml/runs?per_page=1"
        )
        if (
            ci_data
            and isinstance(ci_data.get("workflow_runs"), list)
            and ci_data["workflow_runs"]
        ):
            run = ci_data["workflow_runs"][0]
            conclusion = run.get("conclusion") or run.get("status")
            stats["ci_status"] = conclusion
            stats["ci_date"] = run.get("updated_at")
        else:
            stats["ci_status"] = None
            stats["ci_date"] = None
    else:
        stats["ci_status"] = "n/a"
        stats["ci_date"] = None

    # --- Last release ---
    release = gh_api_single(f"/repos/{repo}/releases/latest")
    if release and isinstance(release, dict) and "tag_name" in release:
        stats["last_release"] = release["tag_name"]
        stats["last_release_date"] = release.get("published_at")
    else:
        stats["last_release"] = None
        stats["last_release_date"] = None

    # --- Commits (30d) ---
    commits = gh_api(f"/repos/{repo}/commits?since={since_30d}&per_page=100")
    commits_list = commits if isinstance(commits, list) else []
    stats["commits_30d"] = len(commits_list)

    # --- Last commit ---
    last_commit = gh_api_single(f"/repos/{repo}/commits?per_page=1")
    if isinstance(last_commit, list) and last_commit:
        c = last_commit[0]
        stats["last_commit"] = c.get("commit", {}).get("committer", {}).get(
            "date"
        ) or c.get("commit", {}).get("author", {}).get("date")
    else:
        stats["last_commit"] = None

    # --- Contributors ---
    contributors = gh_api(f"/repos/{repo}/contributors?per_page=100&anon=0")
    stats["contributors"] = count_list(contributors)

    # --- Code frequency (additions/deletions last 4 weeks) ---
    code_freq = gh_api_single(f"/repos/{repo}/stats/code_frequency")
    if isinstance(code_freq, list) and code_freq:
        # Each item: [week_unix_ts, additions, deletions]
        recent_4w = code_freq[-4:] if len(code_freq) >= 4 else code_freq
        stats["additions_30d"] = sum(
            w[1] for w in recent_4w if isinstance(w, list) and len(w) >= 3
        )
        stats["deletions_30d"] = abs(
            sum(w[2] for w in recent_4w if isinstance(w, list) and len(w) >= 3)
        )
    else:
        stats["additions_30d"] = 0
        stats["deletions_30d"] = 0

    # --- Python file count (via git tree) ---
    tree = gh_api_single(f"/repos/{repo}/git/trees/HEAD?recursive=1")
    if tree and isinstance(tree.get("tree"), list):
        py_files = [
            f
            for f in tree["tree"]
            if f.get("type") == "blob" and f.get("path", "").endswith(".py")
        ]
        stats["py_files"] = len(py_files)
        stats["code_size_kb"] = round(sum(f.get("size", 0) for f in py_files) / 1024, 1)
    else:
        stats["py_files"] = 0
        stats["code_size_kb"] = 0

    return stats


def render_dashboard(providers: list[dict], all_stats: dict[str, dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Provider Dashboard",
        "",
        f"*Last updated: {now}*",
        "",
        "---",
        "",
        "## PRs & Issues",
        "",
        "| Provider | Type | Open PRs | Draft | Merged 30d | 🐛 Bugs | 💡 Enhance | 🚨 CI Incidents | Issues | CI Status | Last Release |",
        "|----------|------|:--------:|:-----:|:----------:|:-------:|:----------:|:---------------:|:------:|:---------:|:------------:|",
    ]

    totals = {
        "pr_open": 0,
        "pr_draft": 0,
        "pr_merged_30d": 0,
        "bugs": 0,
        "enhancements": 0,
        "incidents": 0,
        "issues_open": 0,
    }

    for p in providers:
        repo = p["repo"]
        s = all_stats.get(repo, {})
        name = p.get("display_name", p["domain"])
        ptype = p.get("provider_type", "")
        ptype_short = {
            "music_provider": "🎵 Music",
            "player_provider": "🔊 Player",
            "server_fork": "🔧 Fork",
        }.get(ptype, ptype)
        repo_url = f"https://github.com/{repo}"

        ci_raw = s.get("ci_status")
        if ci_raw == "n/a":
            ci_cell = "—"
        else:
            ci_cell = ci_emoji(ci_raw)
            if s.get("ci_date"):
                ci_cell += f" {format_date(s['ci_date'])}"

        release = s.get("last_release") or "—"
        if release != "—" and s.get("last_release_date"):
            release = f"{release} ({format_date(s['last_release_date'])})"

        row = (
            f"| [{name}]({repo_url}) "
            f"| {ptype_short} "
            f"| {s.get('pr_open', '?')} "
            f"| {s.get('pr_draft', '?')} "
            f"| {s.get('pr_merged_30d', '?')} "
            f"| {s.get('bugs', '?')} "
            f"| {s.get('enhancements', '?')} "
            f"| {s.get('incidents', '?')} "
            f"| {s.get('issues_open', '?')} "
            f"| {ci_cell} "
            f"| {release} |"
        )
        lines.append(row)

        for k in totals:
            totals[k] += s.get(k, 0) if isinstance(s.get(k), int) else 0

    totals_row = (
        f"| **Total** | — "
        f"| **{totals['pr_open']}** "
        f"| **{totals['pr_draft']}** "
        f"| **{totals['pr_merged_30d']}** "
        f"| **{totals['bugs']}** "
        f"| **{totals['enhancements']}** "
        f"| **{totals['incidents']}** "
        f"| **{totals['issues_open']}** "
        f"| — | — |"
    )
    lines.extend(["", totals_row, ""])

    # --- Codebase section ---
    lines.extend(
        [
            "---",
            "",
            "## Codebase",
            "",
            "| Provider | 🐍 Python Files | 📦 Code Size | 👥 Contributors |",
            "|----------|:--------------:|:------------:|:---------------:|",
        ]
    )

    for p in providers:
        repo = p["repo"]
        s = all_stats.get(repo, {})
        name = p.get("display_name", p["domain"])
        repo_url = f"https://github.com/{repo}"
        lines.append(
            f"| [{name}]({repo_url}) "
            f"| {s.get('py_files', '?')} "
            f"| {s.get('code_size_kb', '?')} KB "
            f"| {s.get('contributors', '?')} |"
        )

    # --- Development intensity section ---
    lines.extend(
        [
            "",
            "---",
            "",
            "## Development Intensity (last 30 days)",
            "",
            "| Provider | 📝 Commits | Last Commit | ➕ Additions | ➖ Deletions |",
            "|----------|:----------:|:-----------:|:------------:|:------------:|",
        ]
    )

    for p in providers:
        repo = p["repo"]
        s = all_stats.get(repo, {})
        name = p.get("display_name", p["domain"])
        repo_url = f"https://github.com/{repo}"
        lines.append(
            f"| [{name}]({repo_url}) "
            f"| {s.get('commits_30d', '?')} "
            f"| {format_date(s.get('last_commit'))} "
            f"| +{s.get('additions_30d', 0):,} "
            f"| -{s.get('deletions_30d', 0):,} |"
        )

    lines.extend(["", "---", ""])

    return "\n".join(lines) + "\n"


def main() -> None:
    if not PROVIDERS_FILE.exists():
        print(f"ERROR: {PROVIDERS_FILE} not found", file=sys.stderr)
        sys.exit(1)

    registry = yaml.safe_load(PROVIDERS_FILE.read_text())
    providers = registry.get("providers", [])

    if not providers:
        print("No providers found in providers.yml", file=sys.stderr)
        sys.exit(1)

    print(f"Collecting stats for {len(providers)} providers...")
    all_stats: dict[str, dict] = {}

    for p in providers:
        repo = p["repo"]
        ptype = p.get("provider_type", "")
        print(f"  → {repo} ({ptype})...", end=" ", flush=True)
        try:
            stats = get_provider_stats(repo, ptype)
            all_stats[repo] = stats
            print(
                f"✓  (PRs:{stats['pr_open']} issues:{stats['issues_open']} commits:{stats['commits_30d']})"
            )
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            all_stats[repo] = {}

    print(f"\nWriting {OUTPUT_FILE}...")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(render_dashboard(providers, all_stats))
    print("Done.")


if __name__ == "__main__":
    main()
