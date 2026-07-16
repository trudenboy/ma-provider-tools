import subprocess
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


# ── direction-aware tag walk (issues #104 / #113) ───────────────────────────
#
# A diff against the working tree cannot tell WHO is ahead. A file is only
# genuinely "upstream ahead" if upstream's copy matches none of our historical
# release states — otherwise upstream simply lags behind the provider repo,
# which is exactly what sync-to-fork exists to fix and must not block.


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _commit_tag(root: Path, tag: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "-m", tag)
    _git(root, "tag", tag)


def test_tag_walk_drops_file_matching_previous_release(tmp_path: Path) -> None:
    """Upstream == our v1.0.0 state, working tree moved on → not ahead."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "OLD\n")
    _commit_tag(tmp_path, "v1.0.0")
    _write(tmp_path, "provider/api.py", "NEW LOCAL WORK\n")
    up = {ROOT + "api.py": _blob("OLD\n")}
    out = g.drop_provider_ahead(
        ["provider/api.py"], up, str(tmp_path), DOMAIN, PP, None
    )
    assert out == []


def test_tag_walk_keeps_contributor_edit(tmp_path: Path) -> None:
    """Upstream matches no historical release → genuine contributor change."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "OLD\n")
    _commit_tag(tmp_path, "v1.0.0")
    _write(tmp_path, "provider/api.py", "NEW LOCAL WORK\n")
    up = {ROOT + "api.py": _blob("CONTRIBUTOR EDIT\n")}
    out = g.drop_provider_ahead(
        ["provider/api.py"], up, str(tmp_path), DOMAIN, PP, None
    )
    assert out == ["provider/api.py"]


def test_tag_walk_matches_release_several_tags_back(tmp_path: Path) -> None:
    """Upstream lagging several releases behind still counts as ours."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "V1 CONTENT\n")
    _commit_tag(tmp_path, "v1.0.0")
    _write(tmp_path, "provider/api.py", "V2 CONTENT\n")
    _commit_tag(tmp_path, "v1.1.0")
    _write(tmp_path, "provider/api.py", "V3 CONTENT\n")
    up = {ROOT + "api.py": _blob("V1 CONTENT\n")}
    out = g.drop_provider_ahead(
        ["provider/api.py"], up, str(tmp_path), DOMAIN, PP, None
    )
    assert out == []


def test_tag_walk_new_upstream_file_stays_flagged(tmp_path: Path) -> None:
    """A file that never existed in any release is a contribution."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "x\n")
    _commit_tag(tmp_path, "v1.0.0")
    up = {ROOT + "feature.py": _blob("contributed\n")}
    out = g.drop_provider_ahead(
        ["provider/feature.py"], up, str(tmp_path), DOMAIN, PP, None
    )
    assert out == ["provider/feature.py"]


def test_tag_walk_locally_deleted_file_not_ahead(tmp_path: Path) -> None:
    """We deleted a file since the last release; upstream still has our old
    copy → provider repo is ahead, not upstream."""
    _repo(tmp_path)
    _write(tmp_path, "provider/gone.py", "SHIPPED\n")
    _commit_tag(tmp_path, "v1.0.0")
    (tmp_path / "provider/gone.py").unlink()
    up = {ROOT + "gone.py": _blob("SHIPPED\n")}
    out = g.drop_provider_ahead(
        ["provider/gone.py"], up, str(tmp_path), DOMAIN, PP, None
    )
    assert out == []


def test_tag_walk_applies_transform_to_tag_snapshot(tmp_path: Path) -> None:
    """Tag-state test files get the same forward import rewrite before
    comparison, so a lagging-but-ours test file is not flagged."""
    _repo(tmp_path)
    _write(tmp_path, "tests/test_api.py", "from provider.tools import x\n")
    _commit_tag(tmp_path, "v1.0.0")
    _write(tmp_path, "tests/test_api.py", "from provider.tools import y\n")
    up_text = f"from music_assistant.providers.{DOMAIN}.tools import x\n"
    up = {f"tests/providers/{DOMAIN}/test_api.py": _blob(up_text)}
    out = g.drop_provider_ahead(
        ["tests/test_api.py"], up, str(tmp_path), DOMAIN, PP, None
    )
    assert out == []


def test_tag_walk_without_tags_keeps_everything(tmp_path: Path) -> None:
    """No release history → fail-closed, nothing is dropped."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "x\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "no tags")
    up = {ROOT + "api.py": _blob("y\n")}
    out = g.drop_provider_ahead(
        ["provider/api.py"], up, str(tmp_path), DOMAIN, PP, None
    )
    assert out == ["provider/api.py"]


def test_tag_walk_not_a_git_repo_keeps_everything(tmp_path: Path) -> None:
    """Guard degrades safely when the checkout has no git metadata."""
    up = {ROOT + "api.py": _blob("y\n")}
    out = g.drop_provider_ahead(
        ["provider/api.py"], up, str(tmp_path), DOMAIN, PP, None
    )
    assert out == ["provider/api.py"]


# ── already-ported pass (msx_bridge conftest fallout) ───────────────────────
#
# After a contributor edit merges upstream AND is reverse-ported into the
# provider repo, upstream's copy equals neither any release tag (it carries
# the edit) nor HEAD (which moved on) — the tag walk alone would block every
# sync until the next upstream provider PR merges, though nothing is lost.


def _ported(tmp_path: Path, ahead: list[str], up: dict, blobs: dict) -> list[str]:
    return g.drop_already_ported(
        ahead, up, str(tmp_path), DOMAIN, PP, None, lambda p: blobs.get(p)
    )


def test_ported_pure_deletion_dropped(tmp_path: Path) -> None:
    """Upstream removed a line; HEAD removed it too (and moved on) → drop."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "keep\nlegacy_mock\n")
    _commit_tag(tmp_path, "v1.0.0")
    _write(tmp_path, "provider/api.py", "keep\nnew local work\n")
    up_text = "keep\n"  # tag state minus the removed line
    up = {ROOT + "api.py": _blob(up_text)}
    blobs = {ROOT + "api.py": up_text.encode()}
    assert _ported(tmp_path, ["provider/api.py"], up, blobs) == []


def test_ported_addition_dropped(tmp_path: Path) -> None:
    """Upstream added a line; HEAD contains it (reverse-port merged) → drop."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "base\n")
    _commit_tag(tmp_path, "v1.0.0")
    _write(tmp_path, "provider/api.py", "base\ncontributed line\nlocal work\n")
    up_text = "base\ncontributed line\n"
    up = {ROOT + "api.py": _blob(up_text)}
    blobs = {ROOT + "api.py": up_text.encode()}
    assert _ported(tmp_path, ["provider/api.py"], up, blobs) == []


def test_unported_addition_stays_flagged(tmp_path: Path) -> None:
    """Upstream added a line HEAD does not have → genuine unported edit."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "base\n")
    _commit_tag(tmp_path, "v1.0.0")
    _write(tmp_path, "provider/api.py", "base\nlocal work\n")
    up_text = "base\ncontributed line\n"
    up = {ROOT + "api.py": _blob(up_text)}
    blobs = {ROOT + "api.py": up_text.encode()}
    assert _ported(tmp_path, ["provider/api.py"], up, blobs) == ["provider/api.py"]


def test_unported_deletion_stays_flagged(tmp_path: Path) -> None:
    """Upstream removed a line HEAD still carries → sync would revert it."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "keep\nlegacy_mock\n")
    _commit_tag(tmp_path, "v1.0.0")
    _write(tmp_path, "provider/api.py", "keep\nlegacy_mock\nlocal work\n")
    up_text = "keep\n"
    up = {ROOT + "api.py": _blob(up_text)}
    blobs = {ROOT + "api.py": up_text.encode()}
    assert _ported(tmp_path, ["provider/api.py"], up, blobs) == ["provider/api.py"]


def test_ported_fetch_failure_stays_flagged(tmp_path: Path) -> None:
    """Unfetchable upstream content → fail-closed."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "keep\nlegacy_mock\n")
    _commit_tag(tmp_path, "v1.0.0")
    _write(tmp_path, "provider/api.py", "keep\n")
    up = {ROOT + "api.py": _blob("keep\n")}
    assert _ported(tmp_path, ["provider/api.py"], up, {}) == ["provider/api.py"]


def test_ported_new_upstream_file_stays_flagged(tmp_path: Path) -> None:
    """A file with no HEAD counterpart is a new contribution → keep."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "x\n")
    _commit_tag(tmp_path, "v1.0.0")
    up_text = "contributed\n"
    up = {ROOT + "feature.py": _blob(up_text)}
    blobs = {ROOT + "feature.py": up_text.encode()}
    assert _ported(tmp_path, ["provider/feature.py"], up, blobs) == [
        "provider/feature.py"
    ]


def test_ported_without_tags_stays_flagged(tmp_path: Path) -> None:
    """No release history → fail-closed, nothing dropped."""
    _repo(tmp_path)
    _write(tmp_path, "provider/api.py", "keep\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "no tags")
    up_text = "keep\n"
    up = {ROOT + "api.py": _blob(up_text)}
    blobs = {ROOT + "api.py": up_text.encode()}
    assert _ported(tmp_path, ["provider/api.py"], up, blobs) == ["provider/api.py"]


def test_ported_applies_transform_to_test_files(tmp_path: Path) -> None:
    """The msx scenario in the transformed space: a test-file deletion ported
    into HEAD is recognized through the forward import rewrite."""
    _repo(tmp_path)
    _write(
        tmp_path,
        "tests/conftest.py",
        "from provider.tools import x\nlegacy_mock\n",
    )
    _commit_tag(tmp_path, "v1.0.0")
    _write(
        tmp_path,
        "tests/conftest.py",
        "from provider.tools import x\nnew local fixture\n",
    )
    up_text = f"from music_assistant.providers.{DOMAIN}.tools import x\n"
    up = {f"tests/providers/{DOMAIN}/conftest.py": _blob(up_text)}
    blobs = {f"tests/providers/{DOMAIN}/conftest.py": up_text.encode()}
    assert _ported(tmp_path, ["tests/conftest.py"], up, blobs) == []
