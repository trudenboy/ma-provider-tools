"""An existing upstream/<domain> branch is brought up to date before syncing.

The upstream PR branch (``upstream/<domain>`` in the fork) is only created
from dev once; later syncs check it out as-is. When sibling providers change
upstream meanwhile (e.g. a shared dependency bump), the stale branch fails the
``requirements_all.txt`` pin guard. The sync now merges the latest
music-assistant/server ``dev`` into the existing branch first, and stops with
a clear error on conflicts instead of guessing a resolution.
"""

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STEP_NAME = "Merge latest upstream dev into existing upstream branch"


def _workflow_steps() -> list[dict]:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-sync-to-fork.yml").read_text()
    )
    return workflow["jobs"]["sync"]["steps"]


def _merge_step() -> dict:
    return next(step for step in _workflow_steps() if step.get("name") == STEP_NAME)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content)
    _git(repo, "add", name)
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _setup(tmp_path: Path, *, conflict: bool = False) -> tuple[Path, Path, str]:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "dev")
    _commit(upstream, "requirements_all.txt", "lib==2.0.1\n", "base")

    fork = tmp_path / "ma-server"
    _git(tmp_path, "clone", "-q", str(upstream), str(fork))
    _git(fork, "checkout", "-q", "-b", "upstream/demo")
    if conflict:
        _commit(fork, "requirements_all.txt", "lib==1.9.0\n", "branch edits pin")
    else:
        _commit(fork, "provider.py", "x = 1\n", "provider sync")

    new_dev = _commit(upstream, "requirements_all.txt", "lib==2.1.0\n", "bump lib")
    return upstream, fork, new_dev


def _run(tmp_path: Path, upstream: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _merge_step()["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "UPSTREAM_REPO_URL": str(upstream),
            "TARGET_BRANCH": "upstream/demo",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_step_runs_only_for_existing_upstream_branches() -> None:
    names = [step.get("name") for step in _workflow_steps()]
    assert names.index(STEP_NAME) < names.index("Regenerate requirements_all.txt")
    step = _merge_step()
    assert "steps.branch-check.outputs.exists == 'true'" in step["if"]
    assert "startsWith(inputs.target_branch, 'upstream/')" in step["if"]
    assert step["env"]["UPSTREAM_REPO_URL"] == (
        "https://github.com/music-assistant/server.git"
    )


def test_merges_new_upstream_dev_and_keeps_branch_commits(tmp_path: Path) -> None:
    upstream, fork, new_dev = _setup(tmp_path)

    result = _run(tmp_path, upstream)

    assert result.returncode == 0, result.stderr
    _git(fork, "merge-base", "--is-ancestor", new_dev, "HEAD")
    assert (fork / "requirements_all.txt").read_text() == "lib==2.1.0\n"
    assert (fork / "provider.py").exists()


def test_up_to_date_branch_is_left_unchanged(tmp_path: Path) -> None:
    upstream, fork, _ = _setup(tmp_path)
    assert _run(tmp_path, upstream).returncode == 0
    head = _git(fork, "rev-parse", "HEAD")

    result = _run(tmp_path, upstream)

    assert result.returncode == 0, result.stderr
    assert _git(fork, "rev-parse", "HEAD") == head


def test_conflict_fails_clearly_and_leaves_branch_clean(tmp_path: Path) -> None:
    upstream, fork, _ = _setup(tmp_path, conflict=True)
    head = _git(fork, "rev-parse", "HEAD")

    result = _run(tmp_path, upstream)

    assert result.returncode != 0
    assert "::error::" in result.stdout + result.stderr
    assert _git(fork, "rev-parse", "HEAD") == head
    assert _git(fork, "status", "--porcelain") == ""


def _commit_step_script() -> str:
    step = next(s for s in _workflow_steps() if s.get("name") == "Commit and push")
    return (
        step["run"]
        .replace("${{ inputs.target_branch || 'integration/dev' }}", "upstream/demo")
        .replace("${{ env.DOMAIN }}", "demo")
        .replace("${{ github.event.repository.name }}", "provider")
        .replace("${{ steps.tag.outputs.version }}", "v1.0.0")
    )


def test_merge_commit_is_pushed_without_provider_changes(tmp_path: Path) -> None:
    upstream, fork, new_dev = _setup(tmp_path)
    remote = tmp_path / "fork-remote.git"
    _git(tmp_path, "clone", "-q", "--bare", str(fork), str(remote))
    _git(fork, "remote", "set-url", "origin", str(remote))
    _git(fork, "fetch", "-q", "origin")
    assert _run(tmp_path, upstream).returncode == 0

    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _commit_step_script()],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    pushed = _git(remote, "rev-parse", "refs/heads/upstream/demo")
    assert pushed == _git(fork, "rev-parse", "HEAD")
    _git(remote, "merge-base", "--is-ancestor", new_dev, pushed)


def test_conflict_only_in_provider_owned_paths_is_resolved(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "dev")
    manifest = Path("music_assistant/providers/demo/manifest.json")
    (upstream / manifest.parent).mkdir(parents=True)
    _commit(upstream, str(manifest), '{"req": "lib==2.0.1"}\n', "base")

    fork = tmp_path / "ma-server"
    _git(tmp_path, "clone", "-q", str(upstream), str(fork))
    _git(fork, "checkout", "-q", "-b", "upstream/demo")
    _commit(fork, str(manifest), '{"req": "lib==2.0.1", "v": "4.3.5"}\n', "provider sync")
    new_dev = _commit(upstream, str(manifest), '{"req": "lib==2.1.0"}\n', "bump lib")
    _commit(upstream, "requirements_all.txt", "lib==2.1.0\n", "bump requirements")

    result = _run(tmp_path, upstream)

    assert result.returncode == 0, result.stdout + result.stderr
    _git(fork, "merge-base", "--is-ancestor", new_dev, "HEAD")
    assert _git(fork, "status", "--porcelain") == ""
    assert (fork / "requirements_all.txt").read_text() == "lib==2.1.0\n"
    # The sync overwrites provider-owned files right after; keep the branch side.
    assert "4.3.5" in (fork / manifest).read_text()
