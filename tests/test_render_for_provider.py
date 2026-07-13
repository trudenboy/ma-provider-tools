"""render_for_provider must handle nested template paths and skip_wrappers
(issue #115: scripts/check_method_order.py.j2 renders into _expected/scripts/
and must not be rendered for providers that skip the wrapper).
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "render_for_provider.py"


def _run(domain: str, out_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--domain",
            domain,
            "--out-dir",
            str(out_dir),
            "scripts/check_method_order.py.j2",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_nested_template_renders_into_subdir(tmp_path: Path) -> None:
    res = _run("yandex_music", tmp_path)
    assert res.returncode == 0, res.stderr
    out = tmp_path / "scripts" / "check_method_order.py"
    assert out.is_file()
    assert "provider" in out.read_text()


def test_skip_wrappers_template_not_rendered(tmp_path: Path) -> None:
    res = _run("ma_server", tmp_path)
    assert res.returncode == 0, res.stderr
    assert not (tmp_path / "scripts" / "check_method_order.py").exists()
