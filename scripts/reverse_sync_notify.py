#!/usr/bin/env python3
"""Open or update a deduped issue in this hub (never in music-assistant/*)."""

from __future__ import annotations

import json
import subprocess


def _gh(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], text=True, capture_output=True, **kw)


def upsert_issue(repo: str, label: str, title: str, body: str) -> int:
    existing = _gh(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--label",
            label,
            "--state",
            "open",
            "--json",
            "number,title",
        ]
    ).stdout
    for item in json.loads(existing or "[]"):
        if item["title"] == title:
            num = item["number"]
            _gh(["issue", "comment", str(num), "--repo", repo, "--body", body])
            return num
    created = _gh(
        [
            "issue",
            "create",
            "--repo",
            repo,
            "--label",
            label,
            "--title",
            title,
            "--body",
            body,
        ]
    ).stdout.strip()
    return int(created.rstrip("/").split("/")[-1]) if created else 0
