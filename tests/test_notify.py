import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reverse_sync_notify as notify  # noqa: E402


def _make_result(
    returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_upsert_issue_label_fallback(monkeypatch):
    """If gh issue create --label fails (label absent), retry without --label."""
    calls: list[list[str]] = []

    def fake_gh(args: list[str], **kw) -> subprocess.CompletedProcess:
        calls.append(list(args))
        if "list" in args:
            return _make_result(0, "[]")
        if "create" in args and "--label" in args:
            # Simulate label not found in hub repo
            return _make_result(1, "", "label 'incident:reverse-sync' not found")
        if "create" in args:
            # Second attempt (without label) succeeds
            return _make_result(0, "https://github.com/foo/bar/issues/42\n")
        return _make_result(0)

    monkeypatch.setattr(notify, "_gh", fake_gh)
    result = notify.upsert_issue(
        "foo/bar", "incident:reverse-sync", "Test title", "body"
    )

    assert result == 42
    create_calls = [c for c in calls if "create" in c]
    assert len(create_calls) == 2, f"expected 2 create calls, got {create_calls}"
    assert "--label" in create_calls[0], "first create should include --label"
    assert "--label" not in create_calls[1], "retry create should omit --label"


def test_upsert_issue_both_create_fail(monkeypatch, capsys):
    """If both create attempts fail, returns 0 and emits a warning."""

    def fake_gh(args: list[str], **kw) -> subprocess.CompletedProcess:
        if "list" in args:
            return _make_result(0, "[]")
        if "create" in args:
            return _make_result(1, "", "gh: network error")
        return _make_result(0)

    monkeypatch.setattr(notify, "_gh", fake_gh)
    result = notify.upsert_issue("foo/bar", "lbl", "T", "B")
    assert result == 0
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "warning" in captured.out.lower()


def test_upsert_issue_list_failure_treated_as_no_match(monkeypatch):
    """gh issue list failure is treated as no existing match, not a crash."""

    def fake_gh(args: list[str], **kw) -> subprocess.CompletedProcess:
        if "list" in args:
            return _make_result(1, "", "rate limit exceeded")
        if "create" in args and "--label" in args:
            return _make_result(0, "https://github.com/foo/bar/issues/7\n")
        return _make_result(0)

    monkeypatch.setattr(notify, "_gh", fake_gh)
    result = notify.upsert_issue("foo/bar", "lbl", "T", "B")
    assert result == 7
