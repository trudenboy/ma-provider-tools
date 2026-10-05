"""Standalone-only provider tests must never be exported upstream.

Both forward paths (``reusable-sync-to-fork.yml`` into the integration fork and
the rendered ``upstream-pr.yml`` into music-assistant/server) copy a provider's
``tests/`` with ``rsync --delete``. Tests that only make sense in the
standalone provider repo (project metadata, setup scripts, provider-local
docs) live in ``tests/standalone/`` (or are the legacy ``test_docs.py``) and
are excluded from both copies.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = [
    REPO / ".github/workflows/reusable-sync-to-fork.yml",
    REPO / "wrappers/upstream-pr.yml.j2",
]
EXPECTED_EXCLUDES = ["test_docs.py", "standalone/"]

_TEST_RSYNC = re.compile(
    r"rsync -av --delete(?P<flags>(?:\s+--exclude='[^']+')*)\s*\\?\s*provider-repo/tests/",
)


def _test_export_excludes(path: Path) -> list[str]:
    matches = list(_TEST_RSYNC.finditer(path.read_text()))
    assert len(matches) == 1, f"{path.name}: expected one tests/ rsync, found {len(matches)}"
    return re.findall(r"--exclude='([^']+)'", matches[0].group("flags"))


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_test_export_excludes_standalone_tests(workflow: Path) -> None:
    assert _test_export_excludes(workflow) == EXPECTED_EXCLUDES


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_export_drops_standalone_tests_and_previously_exported_copies(tmp_path: Path) -> None:
    source = tmp_path / "provider-repo" / "tests"
    (source / "standalone").mkdir(parents=True)
    (source / "test_player.py").write_text("")
    (source / "test_docs.py").write_text("")
    (source / "standalone" / "test_project_consistency.py").write_text("")
    dest = tmp_path / "upstream" / "tests" / "providers" / "demo"
    dest.mkdir(parents=True)
    # Exported by an older sync, before the file moved to tests/standalone/.
    (dest / "test_project_consistency.py").write_text("")

    flags = [f"--exclude={pattern}" for pattern in _test_export_excludes(WORKFLOWS[0])]
    subprocess.run(
        ["rsync", "-a", "--delete", *flags, f"{source}/", f"{dest}/"],
        check=True,
        capture_output=True,
    )

    exported = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*"))
    assert exported == ["test_player.py"]
