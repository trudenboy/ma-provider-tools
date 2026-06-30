#!/usr/bin/env python3
"""Open or update a deduped issue in this hub (never in music-assistant/*)."""

from __future__ import annotations

import json
import subprocess
import sys


def _gh(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], text=True, capture_output=True, **kw)


def upsert_issue(repo: str, label: str, title: str, body: str) -> int:
    # --- find an existing open issue with this title ---
    list_result = _gh(
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
    )
    if list_result.returncode != 0:
        print(
            f"::warning::upsert_issue: gh issue list failed (treating as no match): "
            f"{list_result.stderr.strip()}",
            file=sys.stderr,
        )
        existing_items: list[dict] = []
    else:
        existing_items = json.loads(list_result.stdout or "[]")

    for item in existing_items:
        if item["title"] == title:
            num = item["number"]
            _gh(["issue", "comment", str(num), "--repo", repo, "--body", body])
            return num

    # --- create: attempt with label, fall back to without (label may not exist) ---
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
    )
    if created.returncode != 0:
        # Label may not exist in the hub repo yet — retry without --label.
        created = _gh(
            [
                "issue",
                "create",
                "--repo",
                repo,
                "--title",
                title,
                "--body",
                body,
            ]
        )
        if created.returncode != 0:
            print(
                f"::warning::upsert_issue: gh issue create failed: "
                f"{created.stderr.strip()}",
                file=sys.stderr,
            )
            return 0

    url = created.stdout.strip()
    return int(url.rstrip("/").split("/")[-1]) if url else 0
