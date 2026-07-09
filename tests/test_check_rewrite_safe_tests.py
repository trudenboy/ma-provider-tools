"""Tests for check_rewrite_safe_tests.py — Rule A: import provider patterns."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_rewrite_safe_tests as g  # noqa: E402

DOMAIN = "test_provider"
LINE_LENGTH = 100


# ---------------------------------------------------------------------------
# Unit tests: _IMPORT_PROVIDER_RE regex (Rule A)
# ---------------------------------------------------------------------------


class TestImportProviderRe:
    """Test that the Rule-A regex matches exactly the right lines."""

    # --- forms that MUST be flagged ---

    def test_plain_import_provider(self):
        assert g._IMPORT_PROVIDER_RE.match("import provider")

    def test_dotted_import_provider(self):
        assert g._IMPORT_PROVIDER_RE.match("import provider.debug")

    def test_import_with_inline_comment(self):
        assert g._IMPORT_PROVIDER_RE.match("import provider.debug  # some comment")

    # --- forms that must NOT be flagged ---

    def test_aliased_import_provider_dotted_not_flagged(self):
        """Aliased dotted import is safe again (#99): the rewrite translates the
        import line and the body uses the alias."""
        assert not g._IMPORT_PROVIDER_RE.match(
            "import provider.debug.event_buffer as ev_buf"
        )

    def test_aliased_import_provider_simple_not_flagged(self):
        assert not g._IMPORT_PROVIDER_RE.match("import provider as p")

    def test_indented_aliased_import_not_flagged(self):
        assert not g._IMPORT_PROVIDER_RE.match("    import provider.sub as alias")

    def test_from_provider_import_not_flagged(self):
        assert not g._IMPORT_PROVIDER_RE.match("from provider import X")

    def test_from_provider_sub_import_not_flagged(self):
        assert not g._IMPORT_PROVIDER_RE.match(
            "from provider.debug import event_buffer as ev_buf"
        )

    def test_provider_attribute_access_not_flagged(self):
        """Bare attribute access inside a function body must not match."""
        assert not g._IMPORT_PROVIDER_RE.match("        provider.some_method()")

    def test_unrelated_import_not_flagged(self):
        assert not g._IMPORT_PROVIDER_RE.match("import os")

    def test_import_provider_prefix_not_flagged(self):
        """'import provider_utils' must not match — only 'provider' prefix."""
        assert not g._IMPORT_PROVIDER_RE.match("import provider_utils")


# ---------------------------------------------------------------------------
# Integration tests: _scan_file with tmp_path fixture
# ---------------------------------------------------------------------------


def _make_provider_dir(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal provider fixture: provider/manifest.json + provider/."""
    prov_dir = tmp_path / "provider"
    prov_dir.mkdir()
    (tmp_path / "provider" / "manifest.json").write_text(
        '{"domain": "test_provider"}', encoding="utf-8"
    )
    return prov_dir, tmp_path


@pytest.fixture()
def provider_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return the tmp directory configured as a provider CWD."""
    prov_dir, root = _make_provider_dir(tmp_path)
    monkeypatch.chdir(root)
    return root


class TestScanFile:
    """Integration tests using _scan_file directly."""

    def test_aliased_import_not_flagged(self, provider_root: Path):
        """Aliased imports are safe again (#99) — the rewrite handles the import
        line and the body uses the alias."""
        f = provider_root / "provider" / "mod.py"
        f.write_text("import provider.debug.event_buffer as ev_buf\n", encoding="utf-8")
        issues = g._scan_file(f, domain=DOMAIN, line_length=LINE_LENGTH)
        assert issues == []

    def test_plain_import_flagged(self, provider_root: Path):
        f = provider_root / "provider" / "mod.py"
        f.write_text("import provider\n", encoding="utf-8")
        issues = g._scan_file(f, domain=DOMAIN, line_length=LINE_LENGTH)
        assert len(issues) == 1

    def test_dotted_import_flagged(self, provider_root: Path):
        f = provider_root / "provider" / "mod.py"
        f.write_text("import provider.debug\n", encoding="utf-8")
        issues = g._scan_file(f, domain=DOMAIN, line_length=LINE_LENGTH)
        assert len(issues) == 1

    def test_from_provider_import_safe(self, provider_root: Path):
        f = provider_root / "provider" / "mod.py"
        f.write_text("from provider import X\n", encoding="utf-8")
        issues = g._scan_file(f, domain=DOMAIN, line_length=LINE_LENGTH)
        assert issues == []

    def test_from_provider_sub_import_aliased_safe(self, provider_root: Path):
        f = provider_root / "provider" / "mod.py"
        f.write_text(
            "from provider.debug import event_buffer as ev_buf\n", encoding="utf-8"
        )
        issues = g._scan_file(f, domain=DOMAIN, line_length=LINE_LENGTH)
        assert issues == []

    def test_fixture_variable_usage_safe(self, provider_root: Path):
        """provider.some_method() in a function body must not be flagged."""
        f = provider_root / "provider" / "mod.py"
        f.write_text(
            "def test_something(provider):\n    provider.some_method()\n",
            encoding="utf-8",
        )
        issues = g._scan_file(f, domain=DOMAIN, line_length=LINE_LENGTH)
        assert issues == []


# ---------------------------------------------------------------------------
# Rule C: sibling-provider/ paths in tests must be existence-guarded
# ---------------------------------------------------------------------------

_UNGUARDED_CONFTEST = """
import importlib.util
import sys
from pathlib import Path

_PROVIDER_DIR = Path(__file__).resolve().parent.parent / "provider"
_spec = importlib.util.spec_from_file_location("pkg", _PROVIDER_DIR / "__init__.py")
"""

_GUARDED_CONFTEST = """
import importlib.util
import sys
from pathlib import Path

_PROVIDER_DIR = Path(__file__).resolve().parent.parent / "provider"
if _PROVIDER_DIR.is_dir():
    _spec = importlib.util.spec_from_file_location("pkg", _PROVIDER_DIR / "__init__.py")
"""


class TestProviderPathGuard:
    def test_unguarded_sibling_path_flagged(self):
        issues = g._provider_path_guard_issues(
            Path("tests/conftest.py"), _UNGUARDED_CONFTEST
        )
        assert len(issues) == 1
        assert "_PROVIDER_DIR" in issues[0]
        assert "is_dir()" in issues[0]

    def test_guarded_sibling_path_passes(self):
        assert (
            g._provider_path_guard_issues(Path("tests/conftest.py"), _GUARDED_CONFTEST)
            == []
        )

    def test_exists_guard_accepted(self):
        code = _UNGUARDED_CONFTEST + "\nprint(_PROVIDER_DIR.exists())\n"
        assert g._provider_path_guard_issues(Path("tests/conftest.py"), code) == []

    def test_unrelated_paths_ignored(self):
        code = (
            "from pathlib import Path\n"
            'FIXTURES = Path(__file__).parent / "fixtures"\n'
            'OTHER = Path("provider")\n'
        )
        assert g._provider_path_guard_issues(Path("tests/test_x.py"), code) == []

    def test_rule_c_only_applies_to_tests_root(self, provider_root: Path):
        # A provider/-rooted file with the same pattern is not test code and
        # is not synced with the tests rsync — must not be flagged.
        target = provider_root / "provider" / "helper.py"
        target.write_text(_UNGUARDED_CONFTEST, encoding="utf-8")
        issues = g._scan_file(
            Path("provider/helper.py"), domain="test_provider", line_length=100
        )
        assert issues == []

    def test_scan_file_flags_tests_conftest(self, provider_root: Path):
        tests_dir = provider_root / "tests"
        tests_dir.mkdir()
        target = tests_dir / "conftest.py"
        target.write_text(_UNGUARDED_CONFTEST, encoding="utf-8")
        issues = g._scan_file(
            Path("tests/conftest.py"), domain="test_provider", line_length=100
        )
        assert len(issues) == 1
