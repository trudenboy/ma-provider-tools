"""Rendered development tools must use the provider release and runtime contracts."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.distribute import render_wrappers


ROOT = Path(__file__).resolve().parent.parent
MSX_BASELINE = "15003cae786a704959ce4f3933aea30329545cf0"


def _render(domain: str) -> dict[str, str]:
    registry = yaml.safe_load((ROOT / "providers.yml").read_text())
    provider = next(p for p in registry["providers"] if p["domain"] == domain)
    return render_wrappers(provider, registry["providers"])


def test_msx_cleanup_uses_reviewed_baseline_without_disabling_sync_guard() -> None:
    """Intentional retirements use their reviewed source snapshot in every sync entrypoint."""
    rendered = _render("msx_bridge")
    pipeline = yaml.safe_load(rendered[".github/workflows/pipeline.yml"])
    manual = yaml.safe_load(rendered[".github/workflows/sync-to-fork.yml"])
    backport = yaml.safe_load(rendered[".github/workflows/backport.yml"])
    for job in (
        pipeline["jobs"]["sync-integration"],
        pipeline["jobs"]["sync-upstream"],
        manual["jobs"]["sync"],
        backport["jobs"]["backport"],
    ):
        assert job["with"]["upstream_guard_baseline"] == MSX_BASELINE
    for job in (*pipeline["jobs"].values(), backport["jobs"]["backport"]):
        if "with" not in job:
            continue
        assert "ack_upstream_ahead" not in job["with"]
    assert manual["jobs"]["sync"]["with"]["ack_upstream_ahead"] == "${{ inputs.ack_upstream_ahead }}"
    assert manual[True]["workflow_dispatch"]["inputs"]["ack_upstream_ahead"]["default"] is False


@pytest.mark.parametrize(
    ("author", "change_version", "expected"),
    [("contributor", True, 1), ("trudenboy", True, 0), ("contributor", False, 0)],
)
def test_version_guard_enforces_real_root_version_changes(
    tmp_path: Path, author: str, change_version: bool, expected: int
) -> None:
    """Execute the shared guard with the path supplied by the rendered MSX wrapper."""
    wrapper = yaml.safe_load(_render("msx_bridge")[".github/workflows/version-guard.yml"])
    version_path = wrapper["jobs"]["version-guard"]["with"]["version_path"]
    workflow = yaml.safe_load((ROOT / ".github/workflows/reusable-version-guard.yml").read_text())
    guard = workflow["jobs"]["guard"]["steps"][-1]["run"]

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
            cwd=tmp_path,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()

    git("init", "-q")
    (tmp_path / "VERSION").write_text("1.0.0\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / ("VERSION" if change_version else "README.md")).write_text("1.0.1\n")
    git("add", ".")
    git("commit", "-qm", "change")
    result = subprocess.run(
        ["bash", "-e", "-c", guard],
        cwd=tmp_path,
        env={
            **os.environ,
            "PR_AUTHOR": author,
            "OWNER": "trudenboy",
            "BASE_SHA": base,
            "HEAD_SHA": git("rev-parse", "HEAD"),
            "VERSION_PATH": version_path,
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected, result.stdout + result.stderr


def test_player_setup_clones_official_ma_dev(tmp_path: Path) -> None:
    """Run rendered setup with command seams instead of cloning or installing packages."""
    root = tmp_path / "provider-repo"
    script = root / "scripts/setup.sh"
    script.parent.mkdir(parents=True)
    script.write_text(_render("msx_bridge")["scripts/setup.sh"])
    commands = tmp_path / "bin"
    commands.mkdir()
    uv = commands / "uv"
    uv.write_text(
        '#!/bin/sh\nif [ "$1" = venv ]; then\n'
        'printf "%s\\n" "$@" > "$CLONE_ARGS.venv"\n'
        'mkdir -p "$2/bin"\n: > "$2/bin/activate"\nfi\n'
    )
    git = commands / "git"
    git.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$CLONE_ARGS"\n'
        'for target do :; done\nmkdir -p "$target/.git" "$target/music_assistant/providers"\n'
    )
    pre_commit = commands / "pre-commit"
    pre_commit.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CLONE_ARGS.hooks"\n')
    for command in (uv, git, pre_commit):
        command.chmod(0o755)
    log = tmp_path / "clone-args"
    result = subprocess.run(
        ["bash", str(script)],
        env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}", "CLONE_ARGS": str(log)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    args = log.read_text().splitlines()
    assert args[args.index("-b") + 1] == "dev"
    assert "https://github.com/music-assistant/server.git" in args
    venv_args = Path(f"{log}.venv").read_text().splitlines()
    assert venv_args[venv_args.index("--python") + 1] == "3.14"
    assert Path(f"{log}.hooks").read_text().splitlines() == ["install"]


@pytest.mark.parametrize("domain", ["msx_bridge", "fastmcp_server"])
def test_docker_init_reads_provider_manifest_requirements(tmp_path: Path, domain: str) -> None:
    """Execute the bootstrap dependency parser against the same manifest MA loads."""
    script = _render(domain)["scripts/docker-init.sh"]
    manifest_path = (
        "/ma-server/music_assistant/providers/fastmcp_server/manifest.json"
        if domain == "fastmcp_server"
        else "/tmp/provider/manifest.json"
    )
    assert f"python3 - {manifest_path} <<'PYEOF'" in script
    parser = script.split("<<'PYEOF'\n", 1)[1].split("\nPYEOF", 1)[0]
    manifest = tmp_path / "manifest.json"
    requirements = ["segno==1.6.6", "example[async]==2.0"]
    manifest.write_text(json.dumps({"requirements": requirements}))
    result = subprocess.run(
        [sys.executable, "-", str(manifest)],
        input=parser,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == requirements


def test_shared_workspace_uses_current_official_ma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The setup --workspace path must use the same server and Python as standalone setup."""
    spec = importlib.util.spec_from_file_location("dev_workspace", ROOT / "scripts/dev-workspace.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    commands = []

    def record(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(module, "_run", record)
    monkeypatch.setattr(module, "install_provider", lambda *_: None)
    monkeypatch.setattr(module, "build_state", lambda *_: {"providers": []})
    module.cmd_init(argparse.Namespace(dir=str(tmp_path), providers="msx_bridge", all=False))

    clone = next(command for command in commands if command[:2] == ["git", "clone"])
    assert clone[clone.index("-b") + 1] == "dev"
    assert "https://github.com/music-assistant/server.git" in clone
    venv = next(command for command in commands if command[:2] == ["uv", "venv"])
    assert venv[venv.index("--python") + 1] == "3.14"
