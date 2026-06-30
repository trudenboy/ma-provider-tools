#!/usr/bin/env python3
"""Preflight check: is upstream's provider path ahead of the provider repo?

Used by reusable-sync-to-fork.yml before the destructive rsync --delete to
avoid silently reverting un-ported upstream contributions.

Compares content hashes of every file under
music_assistant/providers/<domain>/ in music-assistant/server (read-only)
against the provider repo's mirror, ignoring maintainer-owned files.

Exit 0 = not ahead (safe to sync). Exit 1 = ahead (block unless acked).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _transform as t  # noqa: E402

UPSTREAM = "music-assistant/server"
IGNORE_SUFFIXES = ("VERSION", "translations/en.json")


def _ignored(provider_rel: str) -> bool:
    return any(provider_rel.endswith(s) for s in IGNORE_SUFFIXES)


def diff_files(
    upstream_files: dict[str, str],
    provider_files: dict[str, str],
    domain: str,
    provider_path: str,
) -> list[str]:
    """Return provider-repo-relative paths that differ and are not ignored."""
    out: list[str] = []
    for up_path, up_hash in sorted(upstream_files.items()):
        prov_rel = t.reverse_path(up_path, domain, provider_path)
        if prov_rel is None or _ignored(prov_rel):
            continue
        if provider_files.get(prov_rel) != up_hash:
            out.append(prov_rel)
    return out


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _gh_json(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True
    ).stdout


def _list_upstream_tree(domain: str, ref: str) -> dict[str, str]:
    """Read-only: list files + blob sha under the provider path on upstream."""
    import json

    root = f"music_assistant/providers/{domain}"
    raw = _gh_json(
        [
            "api",
            f"repos/{UPSTREAM}/git/trees/{ref}?recursive=1",
            "--jq",
            '.tree[] | select(.type=="blob") | '
            f'select(.path|startswith("{root}/")) | '
            "{path:.path, sha:.sha}",
        ]
    )
    files: dict[str, str] = {}
    for line in raw.splitlines():
        if line.strip():
            obj = json.loads(line)
            files[obj["path"]] = obj["sha"]
    return files


def _git_blob_sha(repo_dir: str, rel: str) -> str | None:
    p = os.path.join(repo_dir, rel)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as fh:
        data = fh.read()
    # git blob sha = sha1("blob <len>\0<data>"); upstream tree gives git sha,
    # so compute git object id to compare like-for-like.
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--provider-path", required=True)
    ap.add_argument(
        "--provider-dir", required=True, help="checked-out provider repo root"
    )
    ap.add_argument("--upstream-ref", default="HEAD")
    args = ap.parse_args()

    upstream = _list_upstream_tree(args.domain, args.upstream_ref)
    provider: dict[str, str] = {}
    for up_path in upstream:
        rel = t.reverse_path(up_path, args.domain, args.provider_path)
        if rel is None:
            continue
        sha = _git_blob_sha(args.provider_dir, rel)
        if sha is not None:
            provider[rel] = sha

    ahead = diff_files(upstream, provider, args.domain, args.provider_path)
    if ahead:
        print("::warning::Upstream is ahead of the provider repo on:", file=sys.stderr)
        for f in ahead:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("Provider repo is in sync with upstream provider path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
