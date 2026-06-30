import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_upstream_ahead as g  # noqa: E402

DOMAIN = "yandex_music"
PP = "provider/"
ROOT = f"music_assistant/providers/{DOMAIN}/"


def test_identical_not_ahead():
    up = {ROOT + "api.py": "aaa"}
    prov = {"provider/api.py": "aaa"}
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_content_change_is_ahead():
    up = {ROOT + "api.py": "NEW"}
    prov = {"provider/api.py": "OLD"}
    assert g.diff_files(up, prov, DOMAIN, PP) == ["provider/api.py"]


def test_new_upstream_file_is_ahead():
    up = {ROOT + "feature.py": "x"}
    prov = {}
    assert g.diff_files(up, prov, DOMAIN, PP) == ["provider/feature.py"]


def test_version_difference_ignored():
    up = {ROOT + "VERSION": "2.0.0"}
    prov = {"provider/VERSION": "1.0.0"}
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_translations_ignored():
    up = {ROOT + "translations/en.json": "{a}"}
    prov = {"provider/translations/en.json": "{b}"}
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_foreign_upstream_path_ignored():
    up = {"music_assistant/server.py": "x"}
    prov = {}
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_test_file_content_change_is_ahead():
    """A test file under tests/providers/<domain>/ that differs is flagged.

    reverse_path maps tests/providers/yandex_music/test_api.py -> tests/test_api.py,
    so diff_files should return ["tests/test_api.py"] when hashes differ.
    """
    up = {"tests/providers/yandex_music/test_api.py": "NEW"}
    prov = {"tests/test_api.py": "OLD"}
    assert g.diff_files(up, prov, DOMAIN, PP) == ["tests/test_api.py"]


def test_test_file_identical_not_ahead():
    """Test file with identical hash is not flagged."""
    up = {"tests/providers/yandex_music/test_api.py": "SAME"}
    prov = {"tests/test_api.py": "SAME"}
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_test_file_new_upstream_is_ahead():
    """New test file in upstream (absent in provider) is flagged."""
    up = {"tests/providers/yandex_music/test_new.py": "x"}
    prov = {}
    assert g.diff_files(up, prov, DOMAIN, PP) == ["tests/test_new.py"]
