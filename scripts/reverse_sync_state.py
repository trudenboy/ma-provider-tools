#!/usr/bin/env python3
"""Read/write the committed reverse-sync progress state.

state/reverse-sync.json shape:
    { "<domain>": {
        "last_synced_sha": str | null,   # latest upstream SHA on the path (anchor)
        "handled_prs": [int],            # inbound PRs already ported
        "pulls_cursor": str | null,      # ISO updated_at watermark for pass B
        "digest_issue": int | null       # hub digest issue number
    }, ... }
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ENTRY = {
    "last_synced_sha": None,
    "handled_prs": [],
    "pulls_cursor": None,
    "digest_issue": None,
}


def load(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text())


def save(path: Path, data: dict) -> None:
    serialized = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    Path(path).write_text(serialized + "\n")


def entry(data: dict, domain: str) -> dict:
    if domain not in data:
        data[domain] = dict(DEFAULT_ENTRY)
        data[domain]["handled_prs"] = []
    return data[domain]


def mark_handled(data: dict, domain: str, pr: int) -> None:
    handled = entry(data, domain)["handled_prs"]
    if pr not in handled:
        handled.append(pr)


def is_handled(data: dict, domain: str, pr: int) -> bool:
    return pr in entry(data, domain)["handled_prs"]
