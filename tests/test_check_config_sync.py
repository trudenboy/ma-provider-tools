"""check_config_sync must also pin the vendored check_method_order script
(issue #115) so the distributed copy can't silently drift from the template.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_config_sync as ccs  # noqa: E402


def _base_fixture(root: Path) -> None:
    (root / "_expected").mkdir()
    (root / "ruff.toml").write_text("line-length = 88\n")
    (root / "_expected/ruff.toml").write_text("line-length = 88\n")
    (root / "pyproject.toml").write_text("")
    (root / "_expected/pyproject.toml").write_text("")


def _with_expected_script(root: Path, text: str) -> None:
    exp = root / "_expected/scripts/check_method_order.py"
    exp.parent.mkdir(parents=True)
    exp.write_text(text)


def test_method_order_script_in_sync_passes(tmp_path, monkeypatch, capsys):
    _base_fixture(tmp_path)
    _with_expected_script(tmp_path, "SCRIPT\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/check_method_order.py").write_text("SCRIPT\n")
    monkeypatch.chdir(tmp_path)
    assert ccs.main() == 0


def test_method_order_script_drift_fails(tmp_path, monkeypatch, capsys):
    _base_fixture(tmp_path)
    _with_expected_script(tmp_path, "TEMPLATE VERSION\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/check_method_order.py").write_text("LOCAL EDIT\n")
    monkeypatch.chdir(tmp_path)
    assert ccs.main() == 1
    assert "check_method_order" in capsys.readouterr().err


def test_method_order_script_missing_fails(tmp_path, monkeypatch, capsys):
    _base_fixture(tmp_path)
    _with_expected_script(tmp_path, "SCRIPT\n")
    monkeypatch.chdir(tmp_path)
    assert ccs.main() == 1
    assert "missing" in capsys.readouterr().err


def test_no_expected_script_is_skipped(tmp_path, monkeypatch):
    """A provider that skips the wrapper (skip_wrappers) isn't penalised."""
    _base_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert ccs.main() == 0
