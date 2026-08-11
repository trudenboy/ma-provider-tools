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
