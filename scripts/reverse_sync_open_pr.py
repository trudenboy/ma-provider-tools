#!/usr/bin/env python3
"""Open a draft reverse-sync PR in a provider repo for one inbound upstream PR.

Read-only against music-assistant/server (gh pr view + REST combined diff). All
writes target the provider repo only. Best-effort apply opens a draft only when
every touched path has a verified applied, conflicted, or deduplicated outcome.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _transform as t  # noqa: E402

UPSTREAM = "music-assistant/server"

# Maintainer-owned files: never carried into a reverse PR (mirrors the
# forward-sync guard's ignore-list). The PR body promises these are untouched,
# so they must be stripped from the touched-path manifest before snapshots load.
MAINTAINER_OWNED_SUFFIXES = ("VERSION", "translations/en.json")


@dataclass(frozen=True)
class PatchSection:
    target_path: str
    source_path: str
    text: str


@dataclass(frozen=True)
class FileSnapshot:
    content: bytes
    mode: str


@dataclass(frozen=True)
class SnapshotSection:
    source_path: str
    target_path: str
    base: FileSnapshot | None
    incoming: FileSnapshot | None
    remove_source: bool = False
    operation: str = "modify"


@dataclass(frozen=True)
class FileApplyResult:
    path: str
    status: str
    strategy: str
    artifacts: tuple[str, ...]
    diagnostic: str


@dataclass(frozen=True)
class PatchApplyResult:
    files: tuple[FileApplyResult, ...]

    @property
    def conflicts(self) -> bool:
        return bool(self.conflicted_paths)

    @property
    def applied_paths(self) -> list[str]:
        return _unique_paths(self.files, "applied")

    @property
    def conflicted_paths(self) -> list[str]:
        return _unique_paths(self.files, "conflicted")

    @property
    def already_present_paths(self) -> list[str]:
        return _unique_paths(self.files, "already_present")


@dataclass(frozen=True)
class LabelFailure:
    label: str
    diagnostic: str


@dataclass(frozen=True)
class DraftPrResult:
    url: str
    reused: bool
    label_failures: tuple[LabelFailure, ...]


def _unique_paths(files: tuple[FileApplyResult, ...], status: str) -> list[str]:
    return list(dict.fromkeys(item.path for item in files if item.status == status))


def _strip_diff_prefix(path: str) -> str:
    return path[2:] if path.startswith(("a/", "b/")) else path


def _split_patch_sections(patch_text: str) -> tuple[PatchSection, ...]:
    """Split a combined git diff into independently applicable file sections."""
    raw_sections: list[str] = []
    current: list[str] = []
    for line in patch_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                raw_sections.append("".join(current))
            current = [line]
        elif current:
            current.append(line)
        elif line.strip():
            raise RuntimeError("patch contains content before its first diff section")
    if current:
        raw_sections.append("".join(current))

    sections: list[PatchSection] = []
    for text in raw_sections:
        try:
            parts = shlex.split(text.splitlines()[0])
        except ValueError as exc:
            raise RuntimeError(f"invalid diff header: {exc}") from exc
        if len(parts) != 4 or parts[:2] != ["diff", "--git"]:
            raise RuntimeError(f"invalid diff header: {text.splitlines()[0]}")
        sections.append(
            PatchSection(
                target_path=_strip_diff_prefix(parts[3]),
                source_path=_strip_diff_prefix(parts[2]),
                text=text,
            )
        )
    return tuple(sections)


def _drop_maintainer_owned(patch_text: str) -> str:
    """Remove diff sections targeting maintainer-owned files (VERSION, en.json).

    The patch is already in provider-repo layout (post reverse_diff). Splits on
    ``diff --git`` and drops any section whose target path ends with a
    maintainer-owned suffix, so snapshot merge can never modify those files.
    """
    kept: list[str] = []
    for section in _split_patch_sections(patch_text):
        if any(
            path.endswith(suffix)
            for path in (section.source_path, section.target_path)
            for suffix in MAINTAINER_OWNED_SUFFIXES
        ):
            continue
        kept.append(section.text)
    return "".join(kept)


def build_branch(domain: str, pr_number: int) -> str:
    return f"reverse-sync/{domain}-pr{pr_number}"


def build_pr_body(pr: dict, domain: str, apply_result: PatchApplyResult) -> str:
    lines = [
        f"Reverse-sync of upstream PR {pr['html_url']} into the `{domain}` provider.",
        "",
        f"Original author: @{pr['user']['login']} (credited via `Co-authored-by`).",
        "",
        "**Maintainer-owned files were NOT touched** — review `VERSION` and "
        "`translations/en.json` manually if the upstream change implies a bump.",
        "",
        "- [ ] Spec filled in (`specs/inprogress/`)",
        "- [ ] CHANGELOG entry finalized",
        "- [ ] Tests pass locally",
    ]
    if apply_result.conflicts:
        conflict_lines = [
            "",
            "> ⚠ Snapshot merge has **conflicts** that need manual resolution.",
            ">",
            "> Conflicted files:",
        ]
        for item in apply_result.files:
            if item.status != "conflicted":
                continue
            artifacts = ", ".join(f"`{path}`" for path in item.artifacts)
            suffix = f" — artifacts: {artifacts}" if artifacts else ""
            conflict_lines.append(f"> - `{item.path}`{suffix}")
        conflict_lines.append("")
        lines[1:1] = conflict_lines
    return "\n".join(lines)


def _build_pr_title(pr: dict, apply_result: PatchApplyResult) -> str:
    prefix = "[needs-human] " if apply_result.conflicts else ""
    return f"{prefix}reverse-sync: {pr['title']} (#{pr['number']})"


def scaffold_paths(domain: str, pr_number: int) -> dict[str, str]:
    spec = f"specs/inprogress/reverse-sync-pr{pr_number}.md"
    return {
        spec: (
            f"# Reverse-sync: upstream PR #{pr_number}\n\n"
            "WIP=1\n\n"
            f"Ported from music-assistant/server#{pr_number} into `{domain}`.\n\n"
            "## Summary\n\n_TODO: describe the change._\n"
        ),
        "CHANGELOG.md": f"- Reverse-synced upstream PR #{pr_number} (WIP)\n",
    }


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, **kw)


def _fetch_pr_diff(pr_number: int) -> str:
    """Return the upstream PR's combined diff (read-only).

    The combined REST diff is used only as a manifest of paths touched by the
    PR. File contents come from immutable base/head commit snapshots.
    """
    return _run(
        [
            "gh",
            "api",
            f"repos/{UPSTREAM}/pulls/{pr_number}",
            "-H",
            "Accept: application/vnd.github.diff",
        ],
        capture_output=True,
        check=True,
    ).stdout


def _create_draft_pr(
    provider_repo: str,
    default_branch: str,
    branch: str,
    title: str,
    body: str,
    labels: list[str],
    *,
    existing: dict | None = None,
) -> DraftPrResult:
    """Create a draft PR or update a verified bot-owned draft in place."""
    if existing is None:
        res = _run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                provider_repo,
                "--base",
                default_branch,
                "--head",
                branch,
                "--draft",
                "--title",
                title,
                "--body",
                body,
            ],
            capture_output=True,
        )
        if res.returncode != 0:
            raise RuntimeError(
                f"gh pr create failed (rc={res.returncode}): {res.stderr.strip()}"
            )
        url = res.stdout.strip()
        try:
            pr_number = int(url.rstrip("/").rsplit("/", 1)[-1])
        except ValueError as exc:
            raise RuntimeError(
                f"gh pr create returned an invalid URL: {url!r}"
            ) from exc
        reused = False
    else:
        pr_number = int(existing["number"])
        update = _run(
            [
                "gh",
                "api",
                f"repos/{provider_repo}/pulls/{pr_number}",
                "--method",
                "PATCH",
                "-f",
                f"title={title}",
                "-f",
                f"body={body}",
                "-f",
                f"base={default_branch}",
            ],
            capture_output=True,
        )
        if update.returncode != 0:
            raise RuntimeError(
                f"provider PR update failed (rc={update.returncode}): "
                f"{update.stderr.strip()}"
            )
        url = existing["html_url"]
        if update.stdout.strip():
            try:
                url = json.loads(update.stdout).get("html_url", url)
            except json.JSONDecodeError:
                pass
        reused = True

    failures: list[LabelFailure] = []
    for label in labels:
        failure = _add_label(provider_repo, pr_number, label)
        if failure is not None:
            failures.append(failure)
            print(
                f"::warning::could not apply label '{label}' to {url}: "
                f"{failure.diagnostic}",
                file=sys.stderr,
                flush=True,
            )
    if reused and "needs-human" not in labels:
        failure = _remove_label(provider_repo, pr_number, "needs-human")
        if failure is not None:
            failures.append(failure)
            print(
                f"::warning::could not remove stale label 'needs-human' from {url}: "
                f"{failure.diagnostic}",
                file=sys.stderr,
                flush=True,
            )
    return DraftPrResult(url, reused, tuple(failures))


# Canonical colors/descriptions, kept in lockstep with wrappers/labels.yml.j2
# so an on-the-fly created label matches the distributed one.
_LABEL_SPECS = {
    "reverse-sync": (
        "0e8a16",
        "PR auto-opened by the reverse-sync radar from an upstream contribution",
    ),
    "needs-human": (
        "d93f0b",
        "Reverse-sync has verified snapshot-merge conflict markers",
    ),
}


def _add_label(provider_repo: str, pr_number: int, label: str) -> LabelFailure | None:
    """Best-effort REST label application with one create-and-retry attempt."""
    add = [
        "gh",
        "api",
        f"repos/{provider_repo}/issues/{pr_number}/labels",
        "--method",
        "POST",
        "-f",
        f"labels[]={label}",
    ]
    first = _run(add, capture_output=True)
    if first.returncode == 0:
        return
    first_diagnostic = first.stderr.strip() or "<no stderr>"
    lookup = _run(
        [
            "gh",
            "api",
            f"repos/{provider_repo}/labels/{quote(label, safe='')}",
            "--method",
            "GET",
        ],
        capture_output=True,
    )
    if lookup.returncode == 0:
        return LabelFailure(label, first_diagnostic)
    lookup_diagnostic = lookup.stderr.strip() or "<no stderr>"
    if not _is_http_404(lookup_diagnostic):
        return LabelFailure(
            label, f"add: {first_diagnostic}; lookup: {lookup_diagnostic}"
        )
    color, desc = _LABEL_SPECS.get(label, ("ededed", ""))
    create = _run(
        [
            "gh",
            "api",
            f"repos/{provider_repo}/labels",
            "--method",
            "POST",
            "-f",
            f"name={label}",
            "-f",
            f"color={color}",
            "-f",
            f"description={desc}",
        ],
        capture_output=True,
    )
    retry = _run(add, capture_output=True)
    if retry.returncode == 0:
        return None
    diagnostic = "; ".join(
        f"{name}: {result.stderr.strip() or '<no stderr>'}"
        for name, result in (("add", first), ("create", create), ("retry", retry))
    )
    return LabelFailure(label, diagnostic)


def _remove_label(
    provider_repo: str, pr_number: int, label: str
) -> LabelFailure | None:
    """Remove a managed label; an already-absent label is success."""
    result = _run(
        [
            "gh",
            "api",
            f"repos/{provider_repo}/issues/{pr_number}/labels/{quote(label, safe='')}",
            "--method",
            "DELETE",
        ],
        capture_output=True,
    )
    if result.returncode == 0 or _is_http_404(result.stderr):
        return None
    return LabelFailure(label, result.stderr.strip() or "<no stderr>")


def _is_http_404(diagnostic: str) -> bool:
    normalized = diagnostic.lower()
    return "http 404" in normalized or "status code 404" in normalized


def _api_json(command: list[str], context: str) -> object:
    result = _run(command, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{context} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{context} returned invalid JSON") from exc


def _find_existing_reverse_pr(
    provider_repo: str,
    default_branch: str,
    branch: str,
    upstream_pr_number: int,
) -> dict | None:
    """Find and ownership-check an open PR for the deterministic head branch."""
    owner = provider_repo.split("/", 1)[0]
    matches = _api_json(
        [
            "gh",
            "api",
            f"repos/{provider_repo}/pulls",
            "--method",
            "GET",
            "-f",
            "state=open",
            "-f",
            f"head={owner}:{branch}",
        ],
        "provider PR lookup",
    )
    if not isinstance(matches, list):
        raise RuntimeError("provider PR lookup returned a non-list response")
    if not matches:
        return None
    if len(matches) != 1:
        raise RuntimeError(
            f"refusing to overwrite {branch}: found {len(matches)} open PRs"
        )

    existing = matches[0]
    number = existing.get("number")
    safe_shape = (
        existing.get("draft") is True
        and existing.get("base", {}).get("ref") == default_branch
        and existing.get("head", {}).get("ref") == branch
        and isinstance(existing.get("head", {}).get("sha"), str)
        and len(existing["head"]["sha"]) == 40
        and isinstance(number, int)
    )
    if not safe_shape:
        raise RuntimeError(
            f"refusing to overwrite {branch}: existing PR is not the expected draft"
        )

    commits = _api_json(
        ["gh", "api", f"repos/{provider_repo}/pulls/{number}/commits"],
        "provider PR commits lookup",
    )
    expected_headline = f"reverse-sync: port {UPSTREAM}#{upstream_pr_number}"
    safe_commit = (
        isinstance(commits, list)
        and len(commits) == 1
        and commits[0].get("author", {}).get("login") == "github-actions[bot]"
        and commits[0].get("commit", {}).get("message", "").splitlines()[0]
        == expected_headline
    )
    files = _api_json(
        ["gh", "api", f"repos/{provider_repo}/pulls/{number}/files"],
        "provider PR files lookup",
    )
    allowed_files = {
        "CHANGELOG.md",
        f"specs/inprogress/reverse-sync-pr{upstream_pr_number}.md",
    }
    safe_files = isinstance(files, list) and all(
        item.get("filename") in allowed_files for item in files
    )
    if not safe_commit or not safe_files:
        raise RuntimeError(
            f"refusing to overwrite {branch}: existing PR contains human changes"
        )
    return existing


def _remote_branch_sha(provider_dir: str, branch: str) -> str | None:
    """Return the exact remote branch SHA without creating a tracking ref."""
    ref = f"refs/heads/{branch}"
    result = _run(
        ["git", "-C", provider_dir, "ls-remote", "--heads", "origin", ref],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"remote branch lookup failed (rc={result.returncode}): "
            f"{result.stderr.strip()}"
        )
    matches = [line.split() for line in result.stdout.splitlines() if line.strip()]
    exact = [parts[0] for parts in matches if len(parts) == 2 and parts[1] == ref]
    if len(exact) > 1:
        raise RuntimeError(f"remote branch lookup returned duplicate refs for {branch}")
    return exact[0] if exact else None


def _verify_remote_branch_ownership(
    provider_dir: str, branch: str, existing: dict | None
) -> None:
    """Fail closed unless the remote ref is absent or owned by the verified PR."""
    remote_sha = _remote_branch_sha(provider_dir, branch)
    if existing is None:
        if remote_sha is not None:
            raise RuntimeError(
                f"refusing to overwrite {branch}: remote branch exists without a "
                "verified open draft PR"
            )
        return
    expected_sha = existing["head"]["sha"]
    if remote_sha != expected_sha:
        raise RuntimeError(
            f"refusing to overwrite {branch}: remote branch moved "
            f"(expected {expected_sha}, found {remote_sha or '<missing>'})"
        )


def _push_reverse_branch(provider_dir: str, branch: str, existing: dict | None) -> None:
    """Create a new branch or replace a verified head with an explicit SHA lease."""
    if existing is None:
        _git_mut(provider_dir, "push", "-u", "origin", branch)
        return
    expected_sha = existing["head"]["sha"]
    lease = f"--force-with-lease=refs/heads/{branch}:{expected_sha}"
    _git_mut(provider_dir, "push", "-u", lease, "origin", branch)


def _fetch_upstream_commits(provider_dir: str, pr_number: int) -> tuple[str, str]:
    """Fetch immutable upstream base/head commits used for snapshot merging."""
    lookup = _run(
        [
            "gh",
            "api",
            f"repos/{UPSTREAM}/pulls/{pr_number}",
            "--jq",
            r'.base.sha + "\t" + .head.sha',
        ],
        capture_output=True,
    )
    if lookup.returncode != 0:
        raise RuntimeError(
            f"upstream snapshot lookup failed (rc={lookup.returncode}): "
            f"{lookup.stderr.strip() or '<no stderr>'}"
        )
    commits = lookup.stdout.strip().split("\t")
    if len(commits) != 2 or not all(commits):
        raise RuntimeError("upstream snapshot lookup returned invalid base/head SHAs")
    base, head = commits
    remote = _run(
        [
            "git",
            "-C",
            provider_dir,
            "remote",
            "add",
            "upstream",
            f"https://github.com/{UPSTREAM}.git",
        ],
        capture_output=True,
    )
    if remote.returncode != 0 and "already exists" not in remote.stderr:
        raise RuntimeError(
            f"could not configure upstream remote: "
            f"{remote.stderr.strip() or '<no stderr>'}"
        )
    for name, commit in (("base", base), ("head", head)):
        fetch = _run(
            ["git", "-C", provider_dir, "fetch", "--depth", "1", "upstream", commit],
            capture_output=True,
        )
        if fetch.returncode != 0:
            raise RuntimeError(
                f"could not fetch upstream {name} {commit}: "
                f"{fetch.stderr.strip() or '<no stderr>'}"
            )
    print(f"Fetched upstream snapshots {base}..{head} for PR#{pr_number}", flush=True)
    return base, head


def _git_mut(provider_dir: str, *args: str) -> subprocess.CompletedProcess:
    """Run a mutating git command; raise RuntimeError on non-zero exit."""
    result = _run(["git", "-C", provider_dir, *args], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result


def _ensure_clean_checkout(provider_dir: str) -> None:
    status = _run(
        ["git", "-C", provider_dir, "status", "--porcelain"],
        capture_output=True,
    )
    if status.returncode != 0:
        raise RuntimeError(
            f"git status failed (rc={status.returncode}): {status.stderr.strip()}"
        )
    if status.stdout.strip():
        raise RuntimeError(
            "provider checkout must be clean before reverse-sync apply: "
            f"{status.stdout.strip()}"
        )


def _changed_paths(provider_dir: str) -> set[str]:
    paths: set[str] = set()
    commands = (
        ["git", "-C", provider_dir, "diff", "--name-only"],
        ["git", "-C", provider_dir, "diff", "--cached", "--name-only"],
        [
            "git",
            "-C",
            provider_dir,
            "ls-files",
            "--others",
            "--exclude-standard",
        ],
    )
    for command in commands:
        result = _run(command, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"{' '.join(command[3:])} failed (rc={result.returncode}): "
                f"{result.stderr.strip()}"
            )
        paths.update(line for line in result.stdout.splitlines() if line)
    return paths


def _current_file_snapshot(provider_dir: str, rel: str) -> FileSnapshot | None:
    path = os.path.join(provider_dir, rel)
    if not os.path.lexists(path):
        return None
    if os.path.islink(path):
        return FileSnapshot(os.readlink(path).encode(), "120000")
    if not os.path.isfile(path):
        raise RuntimeError(f"snapshot path is not a file: {rel}")
    with open(path, "rb") as handle:
        content = handle.read()
    mode = "100755" if os.stat(path).st_mode & 0o111 else "100644"
    return FileSnapshot(content, mode)


def _snapshot_at_commit(
    provider_dir: str, commit: str, upstream_path: str, provider_path: str, domain: str
) -> FileSnapshot | None:
    tree = subprocess.run(
        ["git", "-C", provider_dir, "ls-tree", "-z", commit, "--", upstream_path],
        capture_output=True,
    )
    if tree.returncode != 0:
        raise RuntimeError(
            f"git ls-tree failed for {commit}:{upstream_path}: "
            f"{tree.stderr.decode(errors='replace').strip()}"
        )
    if not tree.stdout:
        return None
    entries = [entry for entry in tree.stdout.split(b"\0") if entry]
    if len(entries) != 1 or b"\t" not in entries[0]:
        raise RuntimeError(f"unexpected git tree entry for {commit}:{upstream_path}")
    metadata, _ = entries[0].split(b"\t", 1)
    parts = metadata.split()
    if len(parts) != 3 or parts[1] != b"blob":
        raise RuntimeError(f"unsupported git tree entry for {commit}:{upstream_path}")
    mode, object_id = parts[0].decode(), parts[2].decode()
    blob = subprocess.run(
        ["git", "-C", provider_dir, "cat-file", "blob", object_id],
        capture_output=True,
    )
    if blob.returncode != 0:
        raise RuntimeError(
            f"git cat-file failed for {commit}:{upstream_path}: "
            f"{blob.stderr.decode(errors='replace').strip()}"
        )
    content = blob.stdout
    if provider_path.startswith("tests/") and provider_path.endswith(".py"):
        try:
            text = content.decode()
        except UnicodeDecodeError as exc:
            raise RuntimeError(
                f"upstream Python test is not UTF-8: {upstream_path}"
            ) from exc
        content = t.reverse_content(provider_path, text, domain).encode()
    return FileSnapshot(content, mode)


def _load_snapshot_sections(
    sections: tuple[PatchSection, ...],
    provider_dir: str,
    base_sha: str,
    head_sha: str,
    domain: str,
    provider_path: str,
) -> tuple[SnapshotSection, ...]:
    """Load touched base/head files and normalize them to provider layout."""
    snapshots: list[SnapshotSection] = []
    for section in sections:
        operation = _patch_operation(section)
        upstream_source = t.forward_path(section.source_path, domain, provider_path)
        upstream_target = t.forward_path(section.target_path, domain, provider_path)
        if upstream_source is None or upstream_target is None:
            raise RuntimeError(
                f"cannot map snapshot paths for {section.source_path} -> "
                f"{section.target_path}"
            )
        snapshot = SnapshotSection(
            source_path=section.source_path,
            target_path=section.target_path,
            base=_snapshot_at_commit(
                provider_dir,
                base_sha,
                upstream_source,
                section.source_path,
                domain,
            ),
            incoming=_snapshot_at_commit(
                provider_dir,
                head_sha,
                upstream_target,
                section.target_path,
                domain,
            ),
            remove_source=operation == "rename",
            operation=operation,
        )
        _validate_snapshot_shape(snapshot)
        snapshots.append(snapshot)
    return tuple(snapshots)


def _patch_operation(section: PatchSection) -> str:
    lines = section.text.splitlines()
    if any(line.startswith("new file mode ") for line in lines):
        return "add"
    if any(line.startswith("deleted file mode ") for line in lines):
        return "delete"
    if any(line.startswith("rename from ") for line in lines):
        return "rename"
    if any(line.startswith("copy from ") for line in lines):
        return "copy"
    return "modify"


def _validate_snapshot_shape(section: SnapshotSection) -> None:
    expected = {
        "add": (False, True),
        "delete": (True, False),
        "modify": (True, True),
        "rename": (True, True),
        "copy": (True, True),
    }
    if section.operation not in expected:
        raise RuntimeError(
            f"unknown snapshot operation {section.operation!r} for "
            f"{section.target_path}"
        )
    actual = (section.base is not None, section.incoming is not None)
    if actual != expected[section.operation]:
        requirements = {
            "add": "requires HEAD and no BASE",
            "delete": "requires BASE and no HEAD",
            "modify": "requires BASE and HEAD",
            "rename": "requires BASE and HEAD",
            "copy": "requires BASE and HEAD",
        }
        raise RuntimeError(
            f"{section.operation} snapshot for {section.target_path} "
            f"{requirements[section.operation]}"
        )


def _write_file_snapshot(
    provider_dir: str, rel: str, snapshot: FileSnapshot | None
) -> None:
    path = os.path.join(provider_dir, rel)
    if snapshot is None:
        if os.path.lexists(path):
            os.unlink(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.lexists(path):
        os.unlink(path)
    if snapshot.mode == "120000":
        os.symlink(snapshot.content.decode(), path)
        return
    if snapshot.mode not in {"100644", "100755"}:
        raise RuntimeError(f"unsupported file mode {snapshot.mode} for {rel}")
    with open(path, "wb") as handle:
        handle.write(snapshot.content)
    os.chmod(path, 0o755 if snapshot.mode == "100755" else 0o644)


def _merge_snapshot_mode(current: str, base: str, incoming: str, rel: str) -> str:
    if current == incoming:
        return current
    if current == base:
        return incoming
    if incoming == base:
        return current
    raise RuntimeError(f"file mode conflict for {rel}: {current}/{base}/{incoming}")


def _three_way_text_snapshot(
    current: FileSnapshot,
    base: FileSnapshot,
    incoming: FileSnapshot,
    rel: str,
) -> tuple[FileSnapshot, bool, str]:
    """Return a diff3 merge, whether it conflicted, and git's diagnostic."""
    if any(state.mode == "120000" for state in (current, base, incoming)):
        raise RuntimeError(f"divergent symlink snapshot cannot be merged: {rel}")
    if any(b"\0" in state.content for state in (current, base, incoming)):
        raise RuntimeError(f"divergent binary snapshot cannot be merged: {rel}")
    mode = _merge_snapshot_mode(current.mode, base.mode, incoming.mode, rel)
    with tempfile.TemporaryDirectory(prefix="reverse-sync-merge-") as temp_dir:
        paths = []
        for name, content in (
            ("provider", current.content),
            ("upstream-base", base.content),
            ("upstream-head", incoming.content),
        ):
            path = os.path.join(temp_dir, name)
            with open(path, "wb") as handle:
                handle.write(content)
            paths.append(path)
        merge = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                "--diff3",
                "-L",
                "provider",
                "-L",
                "upstream-base",
                "-L",
                "upstream-head",
                *paths,
            ],
            capture_output=True,
        )
    conflicted = 1 <= merge.returncode <= 127
    if merge.returncode != 0 and (
        not conflicted or b"<<<<<<< provider\n" not in merge.stdout
    ):
        raise RuntimeError(
            f"git merge-file failed for {rel} (rc={merge.returncode}): "
            f"{merge.stderr.decode(errors='replace').strip()}"
        )
    return (
        FileSnapshot(merge.stdout, mode),
        conflicted,
        merge.stderr.decode(errors="replace").strip(),
    )


def _structural_conflict_snapshot(
    current: FileSnapshot | None,
    base: FileSnapshot | None,
    incoming: FileSnapshot | None,
    rel: str,
) -> FileSnapshot:
    states = tuple(state for state in (current, base, incoming) if state is not None)
    if not states or any(state.mode == "120000" for state in states):
        raise RuntimeError(f"structural symlink conflict cannot be rendered: {rel}")
    if any(b"\0" in state.content for state in states):
        raise RuntimeError(f"structural binary conflict cannot be rendered: {rel}")

    def content(state: FileSnapshot | None, absent: bytes) -> bytes:
        value = state.content if state is not None else absent
        return value if value.endswith(b"\n") else value + b"\n"

    merged = b"".join(
        (
            b"<<<<<<< provider\n",
            content(current, b"<absent in provider>\n"),
            b"||||||| upstream-base\n",
            content(base, b"<absent in upstream base>\n"),
            b"=======\n",
            content(incoming, b"<deleted by upstream>\n"),
            b">>>>>>> upstream-head\n",
        )
    )
    mode_source = current or incoming or base
    if mode_source is None:
        raise RuntimeError(f"empty structural conflict for {rel}")
    mode = mode_source.mode
    return FileSnapshot(merged, mode)


def _merge_snapshot_sections(
    sections: tuple[SnapshotSection, ...], provider_dir: str
) -> PatchApplyResult:
    """Merge normalized upstream base/head snapshots into provider state."""
    _ensure_clean_checkout(provider_dir)
    results: list[FileApplyResult] = []
    for section in sections:
        _validate_snapshot_shape(section)
        source_current = _current_file_snapshot(provider_dir, section.source_path)
        target_current = (
            source_current
            if section.source_path == section.target_path
            else _current_file_snapshot(provider_dir, section.target_path)
        )
        if (
            section.source_path != section.target_path
            and source_current is not None
            and target_current is not None
            and section.remove_source
        ):
            raise RuntimeError(
                f"ambiguous rename state: both {section.source_path} and "
                f"{section.target_path} exist"
            )
        current = (
            target_current
            if source_current is not None
            and target_current is not None
            and not section.remove_source
            else source_current
            if source_current is not None
            else target_current
        )
        current_is_target = (
            section.source_path == section.target_path
            or source_current is None
            or (target_current is not None and not section.remove_source)
        )
        if current_is_target and current == section.incoming:
            results.append(
                FileApplyResult(
                    section.target_path,
                    "already_present",
                    "dedup",
                    (),
                    "already present",
                )
            )
            continue
        if (
            current is None
            and section.base is not None
            and section.incoming is not None
        ):
            _write_file_snapshot(provider_dir, section.target_path, section.incoming)
            results.append(
                FileApplyResult(
                    section.target_path,
                    "applied",
                    "three_way",
                    (),
                    "provider file was absent; materialized upstream head snapshot",
                )
            )
            continue
        if current != section.base:
            if current is None or section.base is None or section.incoming is None:
                merged = _structural_conflict_snapshot(
                    current, section.base, section.incoming, section.target_path
                )
                _write_file_snapshot(provider_dir, section.target_path, merged)
                results.append(
                    FileApplyResult(
                        section.target_path,
                        "conflicted",
                        "three_way",
                        (section.target_path,),
                        "structural snapshot conflict",
                    )
                )
                continue
            merged, conflicted, diagnostic = _three_way_text_snapshot(
                current, section.base, section.incoming, section.target_path
            )
            if (
                section.remove_source
                and section.source_path != section.target_path
                and not conflicted
            ):
                _write_file_snapshot(provider_dir, section.source_path, None)
            _write_file_snapshot(provider_dir, section.target_path, merged)
            status = "conflicted" if conflicted else "applied"
            artifacts = (section.target_path,) if conflicted else ()
            if not conflicted and current_is_target and merged == current:
                status = "already_present"
            results.append(
                FileApplyResult(
                    section.target_path,
                    status,
                    "three_way" if status != "already_present" else "dedup",
                    artifacts,
                    diagnostic
                    or ("already present" if status == "already_present" else ""),
                )
            )
            continue
        if section.remove_source and section.source_path != section.target_path:
            _write_file_snapshot(provider_dir, section.source_path, None)
        _write_file_snapshot(provider_dir, section.target_path, section.incoming)
        results.append(
            FileApplyResult(section.target_path, "applied", "three_way", (), "")
        )
    result = PatchApplyResult(tuple(results))
    _validate_merge_postcondition(sections, result, _changed_paths(provider_dir))
    return result


def _validate_merge_postcondition(
    sections: tuple[SnapshotSection, ...],
    result: PatchApplyResult,
    changed_paths: set[str],
) -> None:
    expected_results = Counter(section.target_path for section in sections)
    actual_results = Counter(item.path for item in result.files)
    allowed_statuses = {"already_present", "applied", "conflicted"}
    allowed_strategies = {"dedup", "three_way"}
    invalid = [
        item
        for item in result.files
        if item.status not in allowed_statuses
        or item.strategy not in allowed_strategies
    ]
    allowed_paths = {
        rel
        for section in sections
        for rel in (section.source_path, section.target_path)
    }
    unexpected = changed_paths - allowed_paths
    outcome_paths: dict[str, set[str]] = {}
    for section in sections:
        outcome_paths.setdefault(section.target_path, set()).update(
            (section.source_path, section.target_path)
        )
    no_changed_path = [
        item.path
        for item in result.files
        if item.status in {"applied", "conflicted"}
        and not (outcome_paths.get(item.path, set()) & changed_paths)
    ]
    if expected_results != actual_results or invalid or unexpected or no_changed_path:
        raise RuntimeError(
            "snapshot merge postcondition failed: "
            f"expected_results={dict(expected_results)}, "
            f"actual_results={dict(actual_results)}, "
            f"invalid_results={invalid}, unexpected_paths={sorted(unexpected)}, "
            f"no_changed_path={no_changed_path}"
        )


def open_reverse_pr(
    domain: str,
    provider_path: str,
    provider_repo: str,
    default_branch: str,
    pr_number: int,
    provider_dir: str,
) -> dict:
    """Open or safely update one reverse-sync PR and return its durable outcome."""
    pr_json = _run(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            UPSTREAM,
            "--json",
            "number,title,url,author",
        ],
        capture_output=True,
        check=True,
    ).stdout
    raw = json.loads(pr_json)
    pr = {
        "number": raw["number"],
        "title": raw["title"],
        "html_url": raw["url"],
        "user": {"login": raw["author"]["login"]},
    }

    patch = _fetch_pr_diff(pr_number)
    reversed_patch = _drop_maintainer_owned(
        t.reverse_diff(patch, domain, provider_path)
    )
    if not reversed_patch.strip():
        return _open_result(skipped=True, reason="no provider-path changes")

    sections = _split_patch_sections(reversed_patch)
    _ensure_clean_checkout(provider_dir)

    branch = build_branch(domain, pr_number)
    # Ownership must be proved before checkout -B and force-push can replace
    # the deterministic branch. Any human-touched PR is fail-closed.
    existing_pr = _find_existing_reverse_pr(
        provider_repo, default_branch, branch, pr_number
    )
    _verify_remote_branch_ownership(provider_dir, branch, existing_pr)

    # Set a committer identity on the clone: CI runners and shallow clones have
    # no user.name/user.email, so `git commit` would fail with rc=128
    # "Author identity unknown". The contributor is credited via the
    # Co-authored-by trailer; the committer is the bot.
    _git_mut(provider_dir, "config", "user.name", "github-actions[bot]")
    _git_mut(
        provider_dir,
        "config",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    )

    _git_mut(provider_dir, "checkout", default_branch)
    _git_mut(provider_dir, "checkout", "-B", branch)

    # Normalize the immutable upstream PR snapshots into provider layout, then
    # merge base/provider/head directly. Unified diff metadata is used only to
    # identify touched paths; git apply and upstream blob-index compatibility
    # are deliberately outside the correctness boundary.
    base_sha, head_sha = _fetch_upstream_commits(provider_dir, pr_number)
    snapshots = _load_snapshot_sections(
        sections,
        provider_dir,
        base_sha,
        head_sha,
        domain,
        provider_path,
    )
    apply_result = _merge_snapshot_sections(snapshots, provider_dir)
    if not apply_result.applied_paths and not apply_result.conflicted_paths:
        return _open_result(skipped=True, reason="already present (all sections)")

    for rel, content in scaffold_paths(domain, pr_number).items():
        dest = os.path.join(provider_dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        mode = "a" if rel.endswith("CHANGELOG.md") and os.path.exists(dest) else "w"
        with open(dest, mode) as fh:
            fh.write(content)

    _git_mut(provider_dir, "add", "-A")
    author = pr["user"]["login"]
    trailer = f"Co-authored-by: {author} <{author}@users.noreply.github.com>"
    _git_mut(
        provider_dir,
        "commit",
        "-m",
        f"reverse-sync: port {UPSTREAM}#{pr_number}\n\n{trailer}",
    )
    # A fresh branch uses a create-only push; an existing verified draft uses
    # the exact head SHA as an explicit lease. Either form fails safely if the
    # remote changes after the ownership check.
    _push_reverse_branch(provider_dir, branch, existing_pr)

    labels = ["reverse-sync"] + (["needs-human"] if apply_result.conflicts else [])
    draft_pr = _create_draft_pr(
        provider_repo,
        default_branch,
        branch,
        _build_pr_title(pr, apply_result),
        build_pr_body(pr, domain, apply_result),
        labels,
        existing=existing_pr,
    )
    return _open_result(
        skipped=False,
        pr_url=draft_pr.url,
        conflicts=apply_result.conflicts,
        reused=draft_pr.reused,
        applied_paths=apply_result.applied_paths,
        conflicted_paths=apply_result.conflicted_paths,
        label_failures=[
            {"label": failure.label, "diagnostic": failure.diagnostic}
            for failure in draft_pr.label_failures
        ],
    )


def _open_result(
    *,
    skipped: bool,
    reason: str | None = None,
    pr_url: str | None = None,
    conflicts: bool = False,
    reused: bool = False,
    applied_paths: list[str] | None = None,
    conflicted_paths: list[str] | None = None,
    label_failures: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "skipped": skipped,
        "reason": reason,
        "pr_url": pr_url,
        "conflicts": conflicts,
        "reused": reused,
        "applied_paths": applied_paths or [],
        "conflicted_paths": conflicted_paths or [],
        "label_failures": label_failures or [],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--provider-path", required=True)
    ap.add_argument("--provider-repo", required=True)
    ap.add_argument("--default-branch", required=True)
    ap.add_argument("--pr-number", type=int, required=True)
    ap.add_argument("--provider-dir", required=True)
    args = ap.parse_args()
    result = open_reverse_pr(
        args.domain,
        args.provider_path,
        args.provider_repo,
        args.default_branch,
        args.pr_number,
        args.provider_dir,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
