import json
import subprocess as sp
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reverse_sync_open_pr as o  # noqa: E402

PR = {
    "number": 4313,
    "title": "Fix track parsing",
    "user": {"login": "alice"},
    "html_url": "https://github.com/music-assistant/server/pull/4313",
}


def test_build_branch():
    assert (
        o.build_branch("fastmcp_server", 4313) == "reverse-sync/fastmcp_server-pr4313"
    )


def test_body_has_upstream_link_and_credit():
    body = o.build_pr_body(PR, "fastmcp_server", conflicts=False)
    assert "music-assistant/server/pull/4313" in body
    assert "@alice" in body
    assert "VERSION" in body  # reminder line about maintainer-owned files


def test_body_flags_conflicts():
    clean = o.build_pr_body(PR, "fastmcp_server", conflicts=False)
    dirty = o.build_pr_body(PR, "fastmcp_server", conflicts=True)
    assert "conflict" in dirty.lower()
    assert "conflict" not in clean.lower()


def test_scaffold_paths():
    paths = o.scaffold_paths("fastmcp_server", 4313)
    spec = next(p for p in paths if p.startswith("specs/inprogress/"))
    assert "WIP=1" in paths[spec]
    assert any(p.endswith("CHANGELOG.md") or "CHANGELOG" in p for p in paths)


def test_push_failure_raises(tmp_path, monkeypatch):
    """push step fails (no remote configured) → RuntimeError is raised, not swallowed."""
    repo = str(tmp_path)
    for cmd in [
        ["git", "-C", repo, "init"],
        ["git", "-C", repo, "config", "user.email", "test@example.com"],
        ["git", "-C", repo, "config", "user.name", "Test"],
    ]:
        sp.run(cmd, check=True, capture_output=True)

    # Discover the branch git init created (may be "main" or "master")
    default_branch = sp.run(
        ["git", "-C", repo, "symbolic-ref", "--short", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    provider_dir = tmp_path / "provider"
    provider_dir.mkdir()
    (provider_dir / "main.py").write_text("# content\n")

    sp.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
    sp.run(["git", "-C", repo, "commit", "-m", "init"], check=True, capture_output=True)

    # Upstream-layout patch (what gh pr diff returns); reverse_diff will map it
    # from music_assistant/providers/test/ → provider/
    upstream_patch = (
        "diff --git a/music_assistant/providers/test/main.py"
        " b/music_assistant/providers/test/main.py\n"
        "--- a/music_assistant/providers/test/main.py\n"
        "+++ b/music_assistant/providers/test/main.py\n"
        "@@ -1 +1,2 @@\n"
        " # content\n"
        "+# new line\n"
    )

    real_run = o._run

    def fake_run(cmd, **kw):
        if cmd[0] == "gh" and "view" in cmd:
            return sp.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    {
                        "number": 999,
                        "title": "Test PR",
                        "url": "https://github.com/music-assistant/server/pull/999",
                        "author": {"login": "testuser"},
                    }
                ),
                "",
            )
        if cmd[0] == "gh" and any("application/vnd.github.diff" in c for c in cmd):
            return sp.CompletedProcess(cmd, 0, upstream_patch, "")
        return real_run(cmd, **kw)

    monkeypatch.setattr(o, "_run", fake_run)

    with pytest.raises(RuntimeError, match="push"):
        o.open_reverse_pr(
            domain="test",
            provider_path="provider/",
            provider_repo="owner/repo",
            default_branch=default_branch,
            pr_number=999,
            provider_dir=repo,
        )


def test_fetch_pr_diff_uses_combined_rest_diff(monkeypatch):
    """Opener must fetch the combined REST diff, not the per-commit `gh pr diff`.

    `gh pr diff` emits one `diff --git` section per commit for a multi-commit
    PR, which breaks the reverse echo-dedup probe; the REST diff media type
    returns a single combined section per file.
    """
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = "diff --git a/x b/x\n"
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return FakeResult()

    monkeypatch.setattr(o, "_run", fake_run)
    out = o._fetch_pr_diff(4392)

    cmd = captured["cmd"]
    assert cmd[:3] == ["gh", "api", "repos/music-assistant/server/pulls/4392"]
    assert "-H" in cmd
    assert "Accept: application/vnd.github.diff" in cmd
    # Must NOT use the per-commit `gh pr diff` form.
    assert not (cmd[:3] == ["gh", "pr", "diff"])
    assert out == "diff --git a/x b/x\n"
