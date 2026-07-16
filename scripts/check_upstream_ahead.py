#!/usr/bin/env python3
"""Preflight check: is upstream's provider path ahead of the provider repo?

Used by reusable-sync-to-fork.yml before the destructive rsync --delete to
avoid silently reverting un-ported upstream contributions.

Compares content hashes of every file under
music_assistant/providers/<domain>/ in music-assistant/server (read-only)
against the provider repo's mirror, ignoring maintainer-owned files.

The comparison is transform-aware: upstream's copy is produced by the sync
boundary (path map + test-import rewrite from scripts/_transform.py, then the
upstream ruff fix/format pass pinned in tests/test_ruff_pass_parity.py), so
the provider tree is pushed through the same transforms into a temp tree
before hashing. Only genuine contributor edits remain as differences. If the
ruff pass cannot run (no network / pin install failure), the guard degrades
to comparing the rewrite-only tree — fail-closed: it can only over-flag,
never silently pass a contributor change.

Exit 0 = not ahead (safe to sync). Exit 1 = ahead (block unless acked).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _transform as t  # noqa: E402

UPSTREAM = "music-assistant/server"
IGNORE_SUFFIXES = ("VERSION", "translations/en.json")

RuffRunner = Callable[[str, list[str]], None]


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


def _sha_git_blob(data: bytes) -> str:
    # git blob sha = sha1("blob <len>\0<data>"); upstream tree gives git shas,
    # so compute git object ids to compare like-for-like.
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def _gh_json(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True
    ).stdout


def _list_upstream_tree(domain: str, ref: str) -> dict[str, str]:
    """Read-only: list files + blob sha under the provider path on upstream.

    Includes both the source root (music_assistant/providers/<domain>/) and
    the test root (tests/providers/<domain>/) so test-only upstream
    contributions are not silently missed.
    """
    import json

    src_root = f"music_assistant/providers/{domain}"
    test_root = f"tests/providers/{domain}"
    raw = _gh_json(
        [
            "api",
            f"repos/{UPSTREAM}/git/trees/{ref}?recursive=1",
            "--jq",
            '.tree[] | select(.type=="blob") | '
            f'select(.path | (startswith("{src_root}/") or startswith("{test_root}/"))) | '
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
        return _sha_git_blob(fh.read())


def _ruff_pin(pyproject_text: str) -> str | None:
    """Extract upstream's exact ruff pin (same regex as the workflow pass)."""
    import re

    m = re.search(r"ruff==[0-9]+\.[0-9]+\.[0-9]+", pyproject_text)
    return m.group(0) if m else None


def _fetch_upstream_pyproject(ref: str) -> str:
    import base64
    import json

    query = f"?ref={ref}" if ref != "HEAD" else ""
    raw = _gh_json(["api", f"repos/{UPSTREAM}/contents/pyproject.toml{query}"])
    return base64.b64decode(json.loads(raw)["content"]).decode()


def _install_ruff(pin: str) -> None:
    """Make ``python -m ruff`` available at the pinned version.

    Tries the current interpreter's pip, then uv (uv-created venvs ship
    without pip), then a bare pip. Already-satisfied pins short-circuit.

    :param pin: Requirement string, e.g. ``ruff==0.15.6``.
    """
    want = pin.partition("==")[2]
    probe = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode == 0 and (not want or want in probe.stdout):
        return
    candidates = [
        [sys.executable, "-m", "pip", "install", "--quiet", pin],
        ["uv", "pip", "install", "--quiet", "--python", sys.executable, pin],
        ["pip", "install", "--quiet", pin],
    ]
    for cmd in candidates:
        try:
            if subprocess.run(cmd, capture_output=True, check=False).returncode == 0:
                return
        except OSError:
            continue
    msg = f"could not install {pin} with any of pip / uv / bare pip"
    raise RuntimeError(msg)


def default_ruff_runner(pyproject_text: str) -> RuffRunner:
    """Boundary ruff pass, mirroring the upstream/* branch of the format step
    in reusable-sync-to-fork.yml / upstream-pr.yml.j2: upstream's exact ruff
    pin, full autofix, then format. Fix/format errors are tolerated (|| true
    in the workflow); only the pin install is a hard failure.
    """

    def run(root: str, targets: list[str]) -> None:
        with open(os.path.join(root, "pyproject.toml"), "w", encoding="utf-8") as fh:
            fh.write(pyproject_text)
        _install_ruff(_ruff_pin(pyproject_text) or "ruff")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--fix",
                "--unsafe-fixes",
                *targets,
            ],
            cwd=root,
            check=False,
            capture_output=True,
        )
        subprocess.run(
            [sys.executable, "-m", "ruff", "format", *targets],
            cwd=root,
            check=False,
            capture_output=True,
        )

    return run


def transformed_contents(
    upstream_files: dict[str, str],
    provider_dir: str,
    domain: str,
    provider_path: str,
    ruff_runner: RuffRunner | None,
) -> dict[str, bytes]:
    """Return provider files as the sync boundary would publish them.

    Writes every provider file that has an upstream counterpart into a temp
    tree in upstream layout (test files get the forward import rewrite), runs
    the boundary ruff pass over it, and returns the resulting bytes keyed by
    provider-relative path.

    :param upstream_files: Upstream tree listing (path -> blob sha).
    :param provider_dir: Checked-out provider repo root.
    :param domain: Provider domain (manifest.json).
    :param provider_path: Provider source path inside the repo (e.g. provider/).
    :param ruff_runner: Boundary pass to run on the temp tree, or None to skip.
    """
    out: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="upstream-ahead-") as tmp:
        written: dict[str, str] = {}
        for up_path in upstream_files:
            rel = t.reverse_path(up_path, domain, provider_path)
            if rel is None or _ignored(rel):
                continue
            src = os.path.join(provider_dir, rel)
            if not os.path.isfile(src):
                continue
            with open(src, "rb") as fh:
                data = fh.read()
            if rel.startswith("tests/") and rel.endswith(".py"):
                data = t.forward_content(rel, data.decode(), domain).encode()
            dest = os.path.join(tmp, up_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
            written[rel] = dest
        # Package stubs so ruff's isort classifies music_assistant imports as
        # first-party exactly like in the real ma-server tree. The stubs are
        # outside the compared roots, so they never appear in the results.
        for stub in (
            "music_assistant/__init__.py",
            "music_assistant/providers/__init__.py",
        ):
            sp = os.path.join(tmp, stub)
            os.makedirs(os.path.dirname(sp), exist_ok=True)
            if not os.path.exists(sp):
                open(sp, "a").close()
        if ruff_runner is not None and written:
            targets = [f"music_assistant/providers/{domain}/"]
            if os.path.isdir(os.path.join(tmp, f"tests/providers/{domain}")):
                targets.append(f"tests/providers/{domain}/")
            try:
                ruff_runner(tmp, targets)
            except Exception as exc:  # noqa: BLE001 -- guard must stay fail-closed
                print(
                    f"::warning::boundary ruff pass failed ({exc}); "
                    "comparing the rewrite-only tree (may over-flag).",
                    file=sys.stderr,
                )
        for rel, dest in written.items():
            with open(dest, "rb") as fh:
                out[rel] = fh.read()
    return out


def transformed_hashes(
    upstream_files: dict[str, str],
    provider_dir: str,
    domain: str,
    provider_path: str,
    ruff_runner: RuffRunner | None,
) -> dict[str, str]:
    """Hash the provider tree as the sync boundary would publish it.

    Same tree construction as :func:`transformed_contents`, returning
    provider-relative git blob hashes of the result.
    """
    return {
        rel: _sha_git_blob(data)
        for rel, data in transformed_contents(
            upstream_files, provider_dir, domain, provider_path, ruff_runner
        ).items()
    }


def _tag_list(provider_dir: str) -> list[str]:
    res = subprocess.run(
        ["git", "-C", provider_dir, "tag", "--sort=-version:refname", "--list", "v*"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        return []
    return [t for t in res.stdout.split() if t]


def _file_at_ref(provider_dir: str, ref: str, rel: str) -> bytes | None:
    res = subprocess.run(
        ["git", "-C", provider_dir, "show", f"{ref}:{rel}"],
        capture_output=True,
        check=False,
    )
    return res.stdout if res.returncode == 0 else None


def drop_provider_ahead(
    ahead: list[str],
    upstream_files: dict[str, str],
    provider_dir: str,
    domain: str,
    provider_path: str,
    ruff_runner: RuffRunner | None,
    max_tags: int = 30,
) -> list[str]:
    """Drop files where upstream merely lags behind a past provider release.

    A working-tree diff cannot tell direction (issues #104/#113): the provider
    repo being ahead — every normal release — used to trip the guard exactly
    like a genuine contributor edit. A file stays flagged only if upstream's
    copy matches *none* of the last ``max_tags`` release states (each snapshot
    pushed through the same boundary transforms). No tags / no git metadata →
    nothing is dropped (fail-closed).
    """
    remaining = set(ahead)
    for tag in _tag_list(provider_dir)[:max_tags]:
        if not remaining:
            break
        with tempfile.TemporaryDirectory(prefix="baseline-") as snap:
            subset: dict[str, str] = {}
            for up_path, up_hash in upstream_files.items():
                rel = t.reverse_path(up_path, domain, provider_path)
                if rel not in remaining:
                    continue
                subset[up_path] = up_hash
                data = _file_at_ref(provider_dir, tag, rel)
                if data is None:
                    continue
                dest = os.path.join(snap, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(data)
            hashes = transformed_hashes(
                subset, snap, domain, provider_path, ruff_runner
            )
        still = set(diff_files(subset, hashes, domain, provider_path))
        for rel in sorted(remaining - still):
            print(
                f"::notice::{rel}: upstream matches provider release {tag} "
                "(provider repo is ahead — not blocking).",
                file=sys.stderr,
            )
        remaining &= still
    return sorted(remaining)


def _fetch_upstream_blob(up_path: str, ref: str) -> bytes | None:
    """Read-only: fetch one file's content from upstream, None on any failure."""
    import base64
    import json

    try:
        raw = _gh_json(["api", f"repos/{UPSTREAM}/contents/{up_path}?ref={ref}"])
        return base64.b64decode(json.loads(raw)["content"])
    except Exception:  # noqa: BLE001 -- fail-closed: caller keeps the file flagged
        return None


def _line_delta(old: bytes, new: bytes) -> tuple[list[str], list[str]]:
    """Return (added, removed) lines of the old -> new edit, context-free."""
    import difflib

    old_lines = old.decode("utf-8", errors="replace").splitlines()
    new_lines = new.decode("utf-8", errors="replace").splitlines()
    added: list[str] = []
    removed: list[str] = []
    for line in difflib.unified_diff(old_lines, new_lines, n=0, lineterm=""):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed.append(line[1:])
    return added, removed


def drop_already_ported(
    ahead: list[str],
    upstream_files: dict[str, str],
    provider_dir: str,
    domain: str,
    provider_path: str,
    ruff_runner: RuffRunner | None,
    fetch_upstream_blob: Callable[[str], bytes | None],
    max_tags: int = 30,
) -> list[str]:
    """Drop files whose upstream edits are already reflected in provider HEAD.

    Complements :func:`drop_provider_ahead`. After a contributor edit merges
    upstream and is reverse-ported into the provider repo, upstream's copy
    equals neither any release tag (it carries the edit) nor HEAD (which has
    moved on with local work) — the tag walk would block every sync until the
    next upstream provider PR merges, even though the destructive rsync would
    lose nothing (same idea as ``_already_present`` in the reverse opener,
    ma-provider-msx-bridge#169 fallout).

    A file is dropped when, against SOME recent release tag state T (in the
    transformed comparison space):

    - every line upstream ADDED relative to T is present in provider HEAD, and
    - every line upstream REMOVED relative to T is absent from provider HEAD.

    A missing HEAD counterpart, an unfetchable upstream copy, or no matching
    tag keeps the file flagged (fail-closed).
    """
    remaining = set(ahead)
    if not remaining:
        return []
    subset = {
        up_path: up_hash
        for up_path, up_hash in upstream_files.items()
        if t.reverse_path(up_path, domain, provider_path) in remaining
    }
    head = transformed_contents(
        subset, provider_dir, domain, provider_path, ruff_runner
    )
    upstream_blobs: dict[str, bytes] = {}
    for up_path in subset:
        data = fetch_upstream_blob(up_path)
        if data is not None:
            upstream_blobs[up_path] = data

    for tag in _tag_list(provider_dir)[:max_tags]:
        if not remaining:
            break
        with tempfile.TemporaryDirectory(prefix="ported-") as snap:
            for up_path in subset:
                rel = t.reverse_path(up_path, domain, provider_path)
                if rel not in remaining:
                    continue
                data = _file_at_ref(provider_dir, tag, rel)
                if data is None:
                    continue
                dest = os.path.join(snap, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(data)
            tag_state = transformed_contents(
                subset, snap, domain, provider_path, ruff_runner
            )
        for up_path in sorted(subset):
            rel = t.reverse_path(up_path, domain, provider_path)
            if rel not in remaining:
                continue
            if up_path not in upstream_blobs or rel not in head or rel not in tag_state:
                continue
            added, removed = _line_delta(tag_state[rel], upstream_blobs[up_path])
            head_lines = set(head[rel].decode("utf-8", errors="replace").splitlines())
            if all(a in head_lines for a in added) and all(
                r not in head_lines for r in removed
            ):
                print(
                    f"::notice::{rel}: upstream edits vs provider release {tag} "
                    "are already reflected in provider HEAD "
                    "(already ported — not blocking).",
                    file=sys.stderr,
                )
                remaining.discard(rel)
    return sorted(remaining)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--provider-path", required=True)
    ap.add_argument(
        "--provider-dir", required=True, help="checked-out provider repo root"
    )
    ap.add_argument("--upstream-ref", default="HEAD")
    ap.add_argument(
        "--no-transform",
        action="store_true",
        help="compare raw file hashes without the boundary transforms",
    )
    ap.add_argument(
        "--no-tag-walk",
        action="store_true",
        help="treat any difference as upstream-ahead without checking whether "
        "upstream merely matches an older provider release",
    )
    ap.add_argument(
        "--max-baseline-tags",
        type=int,
        default=30,
        help="how many release tags (newest first) to check in the tag walk",
    )
    ap.add_argument(
        "--no-ported-check",
        action="store_true",
        help="keep a file flagged even when the upstream edit is already "
        "reflected in provider HEAD (skip the already-ported pass)",
    )
    args = ap.parse_args()

    upstream = _list_upstream_tree(args.domain, args.upstream_ref)
    runner: RuffRunner | None = None
    if args.no_transform:
        provider: dict[str, str] = {}
        for up_path in upstream:
            rel = t.reverse_path(up_path, args.domain, args.provider_path)
            if rel is None:
                continue
            sha = _git_blob_sha(args.provider_dir, rel)
            if sha is not None:
                provider[rel] = sha
    else:
        try:
            runner = default_ruff_runner(_fetch_upstream_pyproject(args.upstream_ref))
        except Exception as exc:  # noqa: BLE001 -- degrade, never skip the guard
            print(
                f"::warning::could not fetch upstream pyproject.toml ({exc}); "
                "comparing the rewrite-only tree (may over-flag).",
                file=sys.stderr,
            )
        provider = transformed_hashes(
            upstream, args.provider_dir, args.domain, args.provider_path, runner
        )

    ahead = diff_files(upstream, provider, args.domain, args.provider_path)
    if ahead and not args.no_tag_walk:
        ahead = drop_provider_ahead(
            ahead,
            upstream,
            args.provider_dir,
            args.domain,
            args.provider_path,
            runner,
            args.max_baseline_tags,
        )
    if ahead and not args.no_tag_walk and not args.no_ported_check:
        ahead = drop_already_ported(
            ahead,
            upstream,
            args.provider_dir,
            args.domain,
            args.provider_path,
            runner,
            lambda up_path: _fetch_upstream_blob(up_path, args.upstream_ref),
            args.max_baseline_tags,
        )
    if ahead:
        print("::warning::Upstream is ahead of the provider repo on:", file=sys.stderr)
        for f in ahead:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("Provider repo is in sync with upstream provider path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
