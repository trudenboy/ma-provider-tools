"""render_for_provider must handle nested template paths and skip_wrappers
(issue #115: scripts/check_method_order.py.j2 renders into _expected/scripts/
and must not be rendered for providers that skip the wrapper).
"""

import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "render_for_provider.py"


def _run(domain: str, out_dir: Path, *templates: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--domain",
            domain,
            "--out-dir",
            str(out_dir),
            *templates,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_nested_template_renders_into_subdir(tmp_path: Path) -> None:
    res = _run("yandex_music", tmp_path, "scripts/check_method_order.py.j2")
    assert res.returncode == 0, res.stderr
    out = tmp_path / "scripts" / "check_method_order.py"
    assert out.is_file()
    assert "provider" in out.read_text()


def test_skip_wrappers_template_not_rendered(tmp_path: Path) -> None:
    res = _run("ma_server", tmp_path, "scripts/check_method_order.py.j2")
    assert res.returncode == 0, res.stderr
    assert not (tmp_path / "scripts" / "check_method_order.py").exists()


def test_fastmcp_runtime_dependencies_match_its_manifest(tmp_path: Path) -> None:
    """A clean FastMCP environment installs every provider runtime dependency."""
    result = _run("fastmcp_server", tmp_path, "pyproject.toml.j2")
    assert result.returncode == 0, result.stderr
    project = tomllib.loads((tmp_path / "pyproject.toml").read_text())

    assert project["project"]["dependencies"] == [
        "fastmcp==3.4.6",
        "prefab-ui==0.20.2",
    ]
