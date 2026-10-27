#!/usr/bin/env python3
"""Mirror upstream Music Assistant agent guidance into ``upstream-guidance/``.

Fetches the files upstream maintains for AI agents and contributors from
``music-assistant/server`` (dev branch, resolved to a commit SHA) and the
organisation-wide ``music-assistant/.github`` repo, writes them byte for byte
under ``upstream-guidance/<source>/<path>``, and records the source SHAs and
a sha256 per file in ``upstream-guidance/lock.json``. ``distribute.py`` ships
the mirror to every provider repo (verbatim through ``VENDORED_FILES``, or
composed into templates through the ``upstream_file`` Jinja global).

Usage:
    python3 scripts/sync_upstream_guidance.py           # refresh the mirror
    python3 scripts/sync_upstream_guidance.py --check   # exit 1 on upstream drift
    python3 scripts/sync_upstream_guidance.py --verify  # offline: files match lock
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
GUIDANCE_DIR = REPO_ROOT / "upstream-guidance"
LOCK_FILE = GUIDANCE_DIR / "lock.json"

SOURCES: dict[str, dict[str, str]] = {
    "server": {"repo": "music-assistant/server", "ref": "dev"},
    "org": {"repo": "music-assistant/.github", "ref": "main"},
}
FIXED_FILES: dict[str, tuple[str, ...]] = {
    "server": (
        "AGENTS.md",
        "DEVELOPMENT.md",
        ".github/copilot-instructions.md",
        ".github/instructions/music-assistant-standards.instructions.md",
        ".github/instructions/music-assistant-cross-repo.instructions.md",
        ".github/instructions/music-assistant-pr-description.instructions.md",
        ".claude/skills/review-pr/SKILL.md",
        ".claude/skills/review-pr/REVIEW_STANDARDS.md",
        ".claude/skills/review-pr/references/new-provider.md",
    ),
    "org": ("AI_POLICY.md", "USAGE_POLICY.md", "CONTRIBUTING.md"),
}
# Controller READMEs are discovered from the upstream tree so a new
# controller is mirrored without touching this script.
CONTROLLER_README_RE = re.compile(r"^music_assistant/controllers/[^/]+/README\.md$")

Fetcher = Callable[[str], bytes]


def http_get(url: str) -> bytes:
    """Fetch a URL, authenticating GitHub API calls when a token is available."""
    request = urllib.request.Request(url)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as resp:
        return resp.read()


def fetch_snapshot(fetch: Fetcher = http_get) -> tuple[dict, dict[str, bytes]]:
    """
    Fetch every mirrored file at a single commit per source.

    :param fetch: Callable returning the body of a URL.
    :return: The lock ``sources`` block and ``{"<source>/<path>": content}``.
    """
    sources: dict[str, dict[str, str]] = {}
    files: dict[str, bytes] = {}
    for name, spec in SOURCES.items():
        repo, ref = spec["repo"], spec["ref"]
        commit = json.loads(
            fetch(f"https://api.github.com/repos/{repo}/commits/{ref}")
        )["sha"]
        sources[name] = {"repo": repo, "ref": ref, "sha": commit}
        paths = list(FIXED_FILES[name])
        if name == "server":
            tree = json.loads(
                fetch(
                    f"https://api.github.com/repos/{repo}/git/trees/{commit}"
                    "?recursive=1"
                )
            )
            paths += sorted(
                entry["path"]
                for entry in tree["tree"]
                if entry["type"] == "blob" and CONTROLLER_README_RE.match(entry["path"])
            )
        for path in paths:
            files[f"{name}/{path}"] = fetch(
                f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"
            )
    return sources, files


def build_lock(sources: dict, files: dict[str, bytes]) -> dict:
    """Return the lock document for a snapshot."""
    return {
        "sources": sources,
        "files": {
            path: hashlib.sha256(content).hexdigest()
            for path, content in sorted(files.items())
        },
    }


def load_lock(lock_file: Path = LOCK_FILE) -> dict:
    """Return the committed lock, or an empty one when none exists yet."""
    if not lock_file.is_file():
        return {"sources": {}, "files": {}}
    return json.loads(lock_file.read_text(encoding="utf-8"))


def mirrored_paths(lock_file: Path = LOCK_FILE) -> list[str]:
    """Return the ``<source>/<path>`` keys recorded in the lock."""
    return sorted(load_lock(lock_file)["files"])


def verify(guidance_dir: Path = GUIDANCE_DIR) -> list[str]:
    """Return problems where the committed mirror disagrees with its lock."""
    lock = load_lock(guidance_dir / "lock.json")
    problems: list[str] = []
    for path, digest in lock["files"].items():
        local = guidance_dir / path
        if not local.is_file():
            problems.append(f"missing: {path}")
        elif hashlib.sha256(local.read_bytes()).hexdigest() != digest:
            problems.append(f"modified: {path}")
    on_disk = {
        p.relative_to(guidance_dir).as_posix()
        for p in guidance_dir.rglob("*")
        if p.is_file() and p.name != "lock.json"
    }
    problems += [f"untracked: {path}" for path in sorted(on_disk - set(lock["files"]))]
    return problems


def write_snapshot(
    sources: dict, files: dict[str, bytes], guidance_dir: Path = GUIDANCE_DIR
) -> list[str]:
    """
    Write a snapshot and its lock, removing files upstream no longer has.

    Nothing is written when no file changed, so a new upstream commit that
    leaves the mirrored files alone does not churn the lock's source SHAs.

    :return: Sorted list of mirrored paths that were added, changed or removed.
    """
    old = load_lock(guidance_dir / "lock.json")["files"]
    lock = build_lock(sources, files)
    changed = sorted(
        path
        for path in set(old) | set(lock["files"])
        if old.get(path) != lock["files"].get(path)
    )
    if not changed:
        return []
    for path in set(old) - set(lock["files"]):
        (guidance_dir / path).unlink(missing_ok=True)
    for path, content in files.items():
        target = guidance_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (guidance_dir / "lock.json").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 on upstream drift")
    mode.add_argument(
        "--verify", action="store_true", help="offline: mirror matches its lock"
    )
    args = parser.parse_args()

    if args.verify:
        problems = verify()
        for problem in problems:
            print(f"upstream-guidance: {problem}", file=sys.stderr)
        return 1 if problems else 0

    sources, files = fetch_snapshot()
    if args.check:
        current = load_lock()["files"]
        drift = build_lock(sources, files)["files"] != current
        if drift:
            print("DRIFT: upstream-guidance/ differs from upstream.", file=sys.stderr)
            return 1
        print("upstream-guidance/ in sync with upstream.")
        return 0

    changed = write_snapshot(sources, files)
    if not changed:
        print("upstream-guidance/ in sync with upstream — no changes.")
    for path in changed:
        print(f"Updated upstream-guidance/{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
