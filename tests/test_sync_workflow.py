import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "a91504084610a817212c17174662cf73a4829bd9"


def _preflight_script() -> str:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-sync-to-fork.yml").read_text()
    )
    steps = workflow["jobs"]["sync"]["steps"]
    script = next(
        step["run"]
        for step in steps
        if step.get("name") == "Preflight — block if upstream is ahead"
    )
    return script.replace(
        "${{ inputs.manifest_path }}", "provider/manifest.json"
    ).replace("${{ inputs.provider_path }}", "provider/")


def _run_preflight(tmp_path: Path, baseline: str) -> list[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ $1 == -c ]]; then printf fastmcp_server; exit 0; fi\n"
        "printf '%s\\0' \"$@\" > \"$CAPTURE\"\n"
    )
    fake_python.chmod(0o755)
    capture = tmp_path / "args"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _preflight_script()],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "CAPTURE": str(capture),
            "UPSTREAM_GUARD_BASELINE": baseline,
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return capture.read_bytes().decode().rstrip("\0").split("\0")


def test_preflight_passes_configured_baseline_as_one_argument(
    tmp_path: Path,
) -> None:
    args = _run_preflight(tmp_path, BASELINE)
    assert args[-2:] == ["--acknowledged-upstream-ref", BASELINE]


def test_preflight_omits_empty_baseline(tmp_path: Path) -> None:
    args = _run_preflight(tmp_path, "")
    assert "--acknowledged-upstream-ref" not in args


def test_workflow_declares_and_maps_upstream_guard_baseline() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-sync-to-fork.yml").read_text()
    )
    trigger = workflow.get("on", workflow.get(True))
    declared = trigger["workflow_call"]["inputs"]["upstream_guard_baseline"]
    assert declared["type"] == "string"
    assert declared["default"] == ""

    steps = workflow["jobs"]["sync"]["steps"]
    preflight = next(
        step
        for step in steps
        if step.get("name") == "Preflight — block if upstream is ahead"
    )
    assert preflight["env"]["UPSTREAM_GUARD_BASELINE"] == (
        "${{ inputs.upstream_guard_baseline }}"
    )


def _version_step() -> dict:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-sync-to-fork.yml").read_text()
    )
    return next(
        step
        for step in workflow["jobs"]["sync"]["steps"]
        if step.get("name") == "Sync VERSION file alongside manifest"
    )


def test_workflow_declares_upstream_exclude_version() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-sync-to-fork.yml").read_text()
    )
    trigger = workflow.get("on", workflow.get(True))
    declared = trigger["workflow_call"]["inputs"]["upstream_exclude_version"]
    assert declared["type"] == "boolean"
    assert declared["default"] is False
    env = _version_step()["env"]
    assert env["UPSTREAM_EXCLUDE_VERSION"] == "${{ inputs.upstream_exclude_version }}"
    assert env["TARGET_BRANCH"] == "${{ inputs.target_branch }}"


def test_version_skipped_only_for_opted_out_upstream_branch(tmp_path: Path) -> None:
    script = _version_step()["run"]
    (tmp_path / "provider-repo").mkdir()
    (tmp_path / "provider-repo" / "VERSION").write_text("1.0.0\n")
    dest = tmp_path / "ma-server" / "music_assistant" / "providers" / "demo"
    dest.mkdir(parents=True)

    cases = [
        ("true", "upstream/demo", False),
        ("true", "integration/dev", True),
        ("false", "upstream/demo", True),
    ]
    for exclude, target, shipped in cases:
        (dest / "VERSION").unlink(missing_ok=True)
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", script],
            env={
                **os.environ,
                "DOMAIN": "demo",
                "UPSTREAM_EXCLUDE_VERSION": exclude,
                "TARGET_BRANCH": target,
            },
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert (dest / "VERSION").exists() is shipped, (exclude, target)
