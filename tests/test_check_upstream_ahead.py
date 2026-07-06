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


# ── transform-aware comparison ──────────────────────────────────────────────


def _blob(data: str) -> str:
    return g._sha_git_blob(data.encode())


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_transformed_test_import_rewrite_matches_upstream(tmp_path: Path) -> None:
    """A test file differing ONLY by the forward import rewrite is not ahead."""
    _write(tmp_path, "tests/test_api.py", "from provider.tools import x\n")
    up_text = f"from music_assistant.providers.{DOMAIN}.tools import x\n"
    up = {f"tests/providers/{DOMAIN}/test_api.py": _blob(up_text)}
    prov = g.transformed_hashes(up, str(tmp_path), DOMAIN, PP, ruff_runner=None)
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_transformed_source_file_passes_through_verbatim(tmp_path: Path) -> None:
    """Provider source files are hashed as-is (no import rewrite)."""
    _write(tmp_path, "provider/api.py", "from provider.tools import x\n")
    up = {ROOT + "api.py": _blob("from provider.tools import x\n")}
    prov = g.transformed_hashes(up, str(tmp_path), DOMAIN, PP, ruff_runner=None)
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_transformed_real_change_still_ahead(tmp_path: Path) -> None:
    """A genuine upstream logic change survives the transform and is flagged."""
    _write(tmp_path, "tests/test_api.py", "from provider.tools import x\n")
    up_text = (
        f"from music_assistant.providers.{DOMAIN}.tools import x\n\nNEW_LOGIC = 1\n"
    )
    up = {f"tests/providers/{DOMAIN}/test_api.py": _blob(up_text)}
    prov = g.transformed_hashes(up, str(tmp_path), DOMAIN, PP, ruff_runner=None)
    assert g.diff_files(up, prov, DOMAIN, PP) == ["tests/test_api.py"]


def test_transformed_missing_provider_file_still_ahead(tmp_path: Path) -> None:
    """A file that exists upstream but not here stays flagged (new contribution)."""
    up = {ROOT + "feature.py": _blob("x = 1\n")}
    prov = g.transformed_hashes(up, str(tmp_path), DOMAIN, PP, ruff_runner=None)
    assert g.diff_files(up, prov, DOMAIN, PP) == ["provider/feature.py"]


def test_ruff_runner_receives_tree_and_reshapes_hashes(tmp_path: Path) -> None:
    """The injected ruff pass runs on the temp tree in upstream layout, and the
    hashes reflect its edits — equality is reached only through the pass."""
    _write(tmp_path, "provider/api.py", '"""One-line summary."""\n')
    up_text = '"""\nOne-line summary.\n"""\n'
    up = {ROOT + "api.py": _blob(up_text)}
    seen: dict[str, object] = {}

    def fake_ruff(root: str, targets: list[str]) -> None:
        seen["targets"] = targets
        p = Path(root) / ROOT / "api.py"
        assert p.is_file()
        p.write_text(up_text)

    prov = g.transformed_hashes(up, str(tmp_path), DOMAIN, PP, ruff_runner=fake_ruff)
    assert g.diff_files(up, prov, DOMAIN, PP) == []
    assert f"music_assistant/providers/{DOMAIN}/" in seen["targets"]


def test_failing_ruff_runner_degrades_to_untransformed_ruff(tmp_path: Path) -> None:
    """A crashing ruff pass must not crash the guard — hashes are computed from
    the rewrite-only tree (fail-closed: more files flagged, never fewer)."""
    _write(tmp_path, "tests/test_api.py", "from provider.tools import x\n")
    up_text = f"from music_assistant.providers.{DOMAIN}.tools import x\n"
    up = {f"tests/providers/{DOMAIN}/test_api.py": _blob(up_text)}

    def broken_ruff(root: str, targets: list[str]) -> None:
        raise RuntimeError("no network")

    prov = g.transformed_hashes(up, str(tmp_path), DOMAIN, PP, ruff_runner=broken_ruff)
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_ruff_pin_extracted_from_pyproject() -> None:
    """The boundary pass pin regex matches the canonical workflow line."""
    text = 'test = [\n  "ruff==0.15.6",\n]\n'
    assert g._ruff_pin(text) == "ruff==0.15.6"
    assert g._ruff_pin("no pin here") is None
