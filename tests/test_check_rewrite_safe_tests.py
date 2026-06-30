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
