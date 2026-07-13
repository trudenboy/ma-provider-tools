"""The distributed check_method_order script (issue #115).

Renders wrappers/scripts/check_method_order.py.j2 the way distribute.py does
and executes it against synthetic provider trees: the vendored rule must
mirror upstream music-assistant/server scripts/check_method_order.py (private
methods live at the bottom of each class), with zero tolerance instead of a
baseline.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parent.parent


def _render() -> str:
    env = Environment(
        loader=FileSystemLoader(str(REPO_ROOT / "wrappers")),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return env.get_template("scripts/check_method_order.py.j2").render(
        provider_path="provider/"
    )


@pytest.fixture
def run_check(tmp_path: Path):
    script = tmp_path / "scripts" / "check_method_order.py"
    script.parent.mkdir(parents=True)
    script.write_text(_render())

    def run(files: dict[str, str]) -> subprocess.CompletedProcess:
        for rel, text in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        return subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True
        )

    return run


def test_clean_ordering_passes(run_check):
    res = run_check(
        {
            "provider/api.py": (
                "class A:\n"
                "    def public(self): ...\n"
                "    def __dunder__(self): ...\n"
                "    def _private(self): ...\n"
                "    def _private_two(self): ...\n"
            )
        }
    )
    assert res.returncode == 0, res.stdout + res.stderr


def test_public_below_private_fails(run_check):
    res = run_check(
        {
            "provider/api.py": (
                "class A:\n    def _private(self): ...\n    def public(self): ...\n"
            )
        }
    )
    assert res.returncode == 1
    assert "'public'" in res.stdout and "'A'" in res.stdout


def test_dunder_below_private_fails(run_check):
    res = run_check(
        {
            "provider/api.py": (
                "class A:\n"
                "    def _private(self): ...\n"
                "    async def __aenter__(self): ...\n"
            )
        }
    )
    assert res.returncode == 1


def test_files_outside_provider_path_ignored(run_check):
    res = run_check(
        {
            "tests/test_x.py": (
                "class A:\n    def _private(self): ...\n    def public(self): ...\n"
            )
        }
    )
    assert res.returncode == 0


def test_syntax_error_file_skipped(run_check):
    res = run_check({"provider/broken.py": "def broken(:\n"})
    assert res.returncode == 0


def test_nested_class_checked(run_check):
    res = run_check(
        {
            "provider/api.py": (
                "class Outer:\n"
                "    class Inner:\n"
                "        def _private(self): ...\n"
                "        def public(self): ...\n"
            )
        }
    )
    assert res.returncode == 1
