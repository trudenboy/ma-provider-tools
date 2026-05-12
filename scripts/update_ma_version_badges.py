#!/usr/bin/env python3
"""Refresh shields.io endpoint badges for the Music Assistant fleet.

For each provider in `providers.yml` (skipping `server_fork`), determine
which Music Assistant channel currently ships the provider and at what
version. Three channels:

- **stable** = `music-assistant/server@main`
- **nightly** = `music-assistant/server@dev`
- **beta**   = `trudenboy/ma-server@integration/dev`

For each channel:
- Probe `music_assistant/providers/<domain>/manifest.json` (presence).
- If present, fetch the sibling `VERSION` file (provider version pin —
  written by the sync pipeline; absent on first bootstrap or for legacy
  syncs).
- Fetch the channel's MA server version from `pyproject.toml::project.version`.

Build a shields.io endpoint badge JSON with a composite message and write
it to `public/badges/<domain>.json`. Idempotent: skips rewrite when content
unchanged.

Authenticated requests use `GH_TOKEN` if present (recommended in CI).

Usage:
    python3 scripts/update_ma_version_badges.py
    python3 scripts/update_ma_version_badges.py --dry-run --domain yandex_music
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
PROVIDERS_FILE = REPO_ROOT / "providers.yml"
BADGES_DIR = REPO_ROOT / "public" / "badges"

UPSTREAM_REPO = "music-assistant/server"
INTEGRATION_REPO = "trudenboy/ma-server"

BADGE_COLOR = "9070B8"
BADGE_LABEL = "Music Assistant"
BADGE_LABEL_COLOR = "555"
CACHE_SECONDS = 14400  # 4 hours; matches cron cadence


@dataclass(frozen=True)
class Channel:
    """One of the three MA channels we sample."""

    name: str  # "stable" / "beta" / "dev"
    repo: str  # GitHub owner/name
    ref: str  # branch / tag


CHANNELS: tuple[Channel, ...] = (
    Channel("stable", UPSTREAM_REPO, "main"),
    Channel("beta", INTEGRATION_REPO, "integration/dev"),
    Channel("dev", UPSTREAM_REPO, "dev"),
)


def _http_get(url: str, *, token: str | None) -> tuple[int, bytes]:
    """Fetch a URL. Returns (status_code, body). 404 maps to (404, b'')."""
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", "ma-provider-tools/update-ma-version-badges")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def _raw_url(repo: str, ref: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"


def _provider_present(channel: Channel, domain: str, token: str | None) -> bool:
    """Check whether `music_assistant/providers/<domain>/manifest.json` exists."""
    url = _raw_url(
        channel.repo, channel.ref, f"music_assistant/providers/{domain}/manifest.json"
    )
    code, _ = _http_get(url, token=token)
    return code == 200


def _provider_version(channel: Channel, domain: str, token: str | None) -> str | None:
    """Return the inlined provider VERSION pin in that channel, or None."""
    url = _raw_url(
        channel.repo, channel.ref, f"music_assistant/providers/{domain}/VERSION"
    )
    code, body = _http_get(url, token=token)
    if code != 200:
        return None
    text = body.decode("utf-8", errors="replace").strip()
    return text or None


def _gh_api_json(path: str, token: str | None) -> object | None:
    """Hit `api.github.com/<path>` and return the parsed JSON or None."""
    url = f"https://api.github.com/{path.lstrip('/')}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", "ma-provider-tools/update-ma-version-badges")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _ma_server_version(channel: Channel, token: str | None) -> str | None:
    """Return a human-readable channel version label.

    - stable: latest non-prerelease tag from `releases/latest`.
    - beta / dev: latest pre-release tag if any, else short SHA of the branch HEAD.

    pyproject.toml is unreliable (placeholder `0.0.0` overwritten by CI at release time).
    """
    if channel.name == "stable":
        data = _gh_api_json(f"repos/{channel.repo}/releases/latest", token)
        if isinstance(data, dict):
            tag = data.get("tag_name")
            if isinstance(tag, str):
                return tag.lstrip("v") or None
        return None

    # For beta and dev we look at the latest release (prereleases included) first;
    # otherwise we fall back to the short SHA of the branch HEAD.
    releases = _gh_api_json(f"repos/{channel.repo}/releases?per_page=5", token)
    if isinstance(releases, list):
        for r in releases:
            if not isinstance(r, dict):
                continue
            target = r.get("target_commitish")
            tag = r.get("tag_name")
            if isinstance(tag, str) and target in (
                channel.ref,
                channel.ref.split("/")[-1],
            ):
                return tag.lstrip("v")
    commit = _gh_api_json(f"repos/{channel.repo}/commits/{channel.ref}", token)
    if isinstance(commit, dict):
        sha = commit.get("sha")
        if isinstance(sha, str) and len(sha) >= 7:
            return sha[:7]
    return None


def _build_message(domain: str, token: str | None) -> str:
    """Compose the badge `message` line.

    Format per channel segment:
        "<channel> v<MAver>[ (v<provVer>)]"
    Channels where the provider is absent are omitted entirely.
    Separator: ` · ` (middle dot).
    """
    segments: list[str] = []
    for ch in CHANNELS:
        if not _provider_present(ch, domain, token):
            continue
        ma_ver = _ma_server_version(ch, token) or "?"
        prov_ver = _provider_version(ch, domain, token)
        if prov_ver:
            segments.append(f"{ch.name} v{ma_ver} (v{prov_ver})")
        else:
            segments.append(f"{ch.name} v{ma_ver}")
    if not segments:
        return "not included"
    return " · ".join(segments)


def _badge_json(domain: str, token: str | None) -> dict:
    return {
        "schemaVersion": 1,
        "label": BADGE_LABEL,
        "message": _build_message(domain, token),
        "color": BADGE_COLOR,
        "labelColor": BADGE_LABEL_COLOR,
        "cacheSeconds": CACHE_SECONDS,
    }


def _write_if_changed(path: Path, payload: dict) -> bool:
    """Write JSON to `path` only when content differs. Returns True if written."""
    new = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    if existing == new:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print badge JSON to stdout; do not write files.",
    )
    parser.add_argument(
        "--domain",
        help="Only refresh the badge for this provider domain (default: all).",
    )
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "WARN: no GH_TOKEN/GITHUB_TOKEN env var — anonymous rate limits apply",
            file=sys.stderr,
        )

    if not PROVIDERS_FILE.is_file():
        print(f"ERROR: {PROVIDERS_FILE} not found", file=sys.stderr)
        return 2

    data = yaml.safe_load(PROVIDERS_FILE.read_text())
    providers = [
        p for p in data.get("providers", []) if p.get("provider_type") != "server_fork"
    ]
    if args.domain:
        providers = [p for p in providers if p.get("domain") == args.domain]
        if not providers:
            print(f"ERROR: domain {args.domain!r} not found", file=sys.stderr)
            return 2

    written = 0
    unchanged = 0
    for provider in providers:
        domain = provider["domain"]
        payload = _badge_json(domain, token)
        if args.dry_run:
            print(f"--- {domain} ---")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            continue
        path = BADGES_DIR / f"{domain}.json"
        if _write_if_changed(path, payload):
            print(f"  wrote {path.relative_to(REPO_ROOT)}: {payload['message']}")
            written += 1
        else:
            unchanged += 1

    if not args.dry_run:
        print(f"\nSummary: {written} written, {unchanged} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
