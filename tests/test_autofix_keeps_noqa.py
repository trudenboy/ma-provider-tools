"""The CI auto-fix must not strip `noqa` markers for rules the local config lacks.

Reverse-sync ports upstream code with `# noqa: S105` / `# noqa: TRY301` before
the provider's synced ``ruff.toml`` enables those rules. Ruff's RUF100 then
sees the markers as unused, the auto-fix commit removes them, and the next
wrapper-sync PR fails lint (yandex-smarthome #135, yandex-disk #39).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _autofix_script() -> str:
    workflow = yaml.safe_load((ROOT / ".github/workflows/reusable-test.yml").read_text())
    step = next(s for s in workflow["jobs"]["lint"]["steps"] if s.get("name") == "Auto-fix lint issues")
    script = step["run"].split("# Safety net", 1)[0]
    return script.replace("${{ inputs.provider_path }}", "provider")


@pytest.mark.skipif(shutil.which("uvx") is None, reason="uvx not available")
def test_autofix_keeps_noqa_for_rules_not_yet_enabled(tmp_path: Path) -> None:
    """A marker for a rule the stale local config does not select survives auto-fix."""
    (tmp_path / "ruff.toml").write_text('[lint]\nselect = ["E", "F", "RUF100"]\n')
    (tmp_path / "provider").mkdir()
    source = 'CONF_TOKEN = "token"  # noqa: S105 - config key\n'
    (tmp_path / "provider" / "constants.py").write_text(source)

    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _autofix_script()],
        cwd=tmp_path,
        env=os.environ,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "provider" / "constants.py").read_text() == source


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not available")
def test_pre_commit_ruff_hook_keeps_noqa_for_rules_not_yet_enabled(tmp_path: Path) -> None:
    """The distributed pre-commit ruff hook leaves the same markers in place."""
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/render_for_provider.py"),
            "--domain",
            "yandex_station",
            "--out-dir",
            str(tmp_path / "rendered"),
            ".pre-commit-config.yaml.j2",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    config = yaml.safe_load((tmp_path / "rendered/.pre-commit-config.yaml").read_text())
    hook = next(h for r in config["repos"] for h in r["hooks"] if h["id"] == "ruff-check")
    entry = hook["entry"].replace("--active ", "")

    repo = tmp_path / "repo"
    (repo / "provider").mkdir(parents=True)
    (repo / "ruff.toml").write_text('[lint]\nselect = ["E", "F", "RUF100"]\n')
    source = 'CONF_TOKEN = "token"  # noqa: S105 - config key\n'
    (repo / "provider" / "constants.py").write_text(source)

    result = subprocess.run(
        ["bash", "-c", f"{entry} provider/constants.py"],
        cwd=repo,
        env=os.environ,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / "provider" / "constants.py").read_text() == source

