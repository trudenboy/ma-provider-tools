#!/usr/bin/env python3
"""Refresh shields.io endpoint badges for the Music Assistant fleet.

For each provider in `providers.yml` (skipping `server_fork`), determine
which Music Assistant release channel currently ships the provider and at
what version. Two channels are tracked, both from the upstream
``music-assistant/server`` repo:

- **stable** = latest non-prerelease release (e.g. ``2.8.7``) — green badge.
- **beta**   = latest prerelease release (e.g. ``2.9.0b10``)   — yellow badge.

The provider manifest / VERSION file is fetched at the **release tag ref**
(so the badge always reflects the exact state shipped in that release,
not the moving HEAD of a branch).

For each channel:
- Probe `music_assistant/providers/<domain>/manifest.json` (presence).
- If present, fetch the sibling `VERSION` file (provider version pin —
  written by the sync pipeline; absent on first bootstrap or for legacy
  syncs).
- Fetch the channel's MA server version from the latest release tag.

Two endpoint-badge JSONs per provider:

    public/badges/<domain>-stable.json  → label "stable" / green
    public/badges/<domain>-beta.json    → label "beta"   / yellow

Message format per channel:
  - provider present AND VERSION file present:  "v<MAver> – v<provVer>"
  - provider present, VERSION absent:           "v<MAver>"
  - provider absent in that channel:            "not included"  (color: lightgrey)

Authenticated requests use `GH_TOKEN` if present (recommended in CI).

Usage:
    python3 scripts/update_ma_version_badges.py
    python3 scripts/update_ma_version_badges.py --dry-run --domain yandex_music
"""

from __future__ import annotations

import argparse
import json
import os
import re
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

COLOR_STABLE = "brightgreen"
COLOR_BETA = "yellow"
COLOR_ABSENT = "lightgrey"
CACHE_SECONDS = 14400  # 4 hours; matches cron cadence


@dataclass(frozen=True)
class Channel:
    """One of the two MA release channels we sample.

    `prerelease=True` resolves the channel ref to the latest prerelease
    tag (e.g. ``2.9.0b10``); `prerelease=False` to the latest stable
    release (``2.8.7``). The resolved tag is used both as the displayed
    MA-server version AND as the raw-content ref for fetching
    ``music_assistant/providers/<domain>/manifest.json`` and ``VERSION``.
    """

    name: str  # "stable" / "beta"
    label: str  # text shown on the badge (left side)
    color: str  # shields.io color (right side) when provider present
    repo: str  # GitHub owner/name
    prerelease: bool  # False → stable release; True → latest prerelease


CHANNELS: tuple[Channel, ...] = (
    Channel("stable", "stable", COLOR_STABLE, UPSTREAM_REPO, prerelease=False),
    Channel("beta", "beta", COLOR_BETA, UPSTREAM_REPO, prerelease=True),
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


def _provider_present(repo: str, ref: str, domain: str, token: str | None) -> bool:
    """Check whether `music_assistant/providers/<domain>/manifest.json` exists at ref."""
    url = _raw_url(repo, ref, f"music_assistant/providers/{domain}/manifest.json")
    code, _ = _http_get(url, token=token)
    return code == 200


def _provider_version(
    repo: str, ref: str, domain: str, token: str | None
) -> str | None:
    """Return the inlined provider VERSION pin at the given ref, or None."""
    url = _raw_url(repo, ref, f"music_assistant/providers/{domain}/VERSION")
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


# PEP 440 beta tag: e.g. "2.9.0b10". Distinguishes beta from dev tags
# (e.g. "2.9.0.dev2026051207"), both of which are GitHub prereleases.
_BETA_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+b\d+$")


def _resolve_release_tag(channel: Channel, token: str | None) -> str | None:
    """Return the GitHub tag for the latest release matching the channel.

    - stable channel: latest non-prerelease release via ``releases/latest``.
    - beta channel: first prerelease whose tag matches the PEP 440 beta
      pattern (``X.Y.ZbN``). Dev tags (``X.Y.Z.devYYYYMMDDHH``) are
      explicitly skipped — beta means a stamped beta release a user might
      install, not the moving dev nightly.
    """
    if not channel.prerelease:
        data = _gh_api_json(f"repos/{channel.repo}/releases/latest", token)
        if isinstance(data, dict):
            tag = data.get("tag_name")
            if isinstance(tag, str) and tag:
                return tag
        return None

    releases = _gh_api_json(f"repos/{channel.repo}/releases?per_page=50", token)
    if isinstance(releases, list):
        for r in releases:
            if not (isinstance(r, dict) and r.get("prerelease")):
                continue
            tag = r.get("tag_name")
            if isinstance(tag, str) and _BETA_TAG_RE.match(tag):
                return tag
    return None


def _channel_badge_json(channel: Channel, domain: str, token: str | None) -> dict:
    """Build the shields.io endpoint payload for one (channel, provider) pair."""
    tag = _resolve_release_tag(channel, token)
    if tag is None:
        return {
            "schemaVersion": 1,
            "label": channel.label,
            "message": "unknown",
            "color": COLOR_ABSENT,
            "cacheSeconds": CACHE_SECONDS,
        }
    ma_ver = tag.lstrip("v")
    if not _provider_present(channel.repo, tag, domain, token):
        return {
            "schemaVersion": 1,
            "label": channel.label,
            "message": f"v{ma_ver} – not included",
            "color": COLOR_ABSENT,
            "cacheSeconds": CACHE_SECONDS,
        }
    prov_ver = _provider_version(channel.repo, tag, domain, token)
    if prov_ver:
        message = f"v{ma_ver} – v{prov_ver}"
    else:
        message = f"v{ma_ver}"
    return {
        "schemaVersion": 1,
        "label": channel.label,
        "message": message,
        "color": channel.color,
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
        for channel in CHANNELS:
            payload = _channel_badge_json(channel, domain, token)
            if args.dry_run:
                print(f"--- {domain} / {channel.name} ---")
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                continue
            path = BADGES_DIR / f"{domain}-{channel.name}.json"
            if _write_if_changed(path, payload):
                print(
                    f"  wrote {path.relative_to(REPO_ROOT)}: "
                    f"{payload['label']} → {payload['message']}"
                )
                written += 1
            else:
                unchanged += 1

    if not args.dry_run:
        print(f"\nSummary: {written} written, {unchanged} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
