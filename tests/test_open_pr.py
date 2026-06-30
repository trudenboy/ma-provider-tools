import base64
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


def test_drop_maintainer_owned_strips_version_and_translations():
    """VERSION and translations/en.json must be removed before apply, so the
    opener's "maintainer-owned files NOT touched" promise holds."""
    patch = (
        "diff --git a/provider/VERSION b/provider/VERSION\n"
        "--- a/provider/VERSION\n+++ b/provider/VERSION\n"
        "@@ -1 +1 @@\n-1.0.0\n+1.0.1\n"
        "diff --git a/provider/config.py b/provider/config.py\n"
        "--- a/provider/config.py\n+++ b/provider/config.py\n"
        "@@ -1 +1,2 @@\n x=1\n+y=2\n"
        "diff --git a/provider/translations/en.json b/provider/translations/en.json\n"
        "--- a/provider/translations/en.json\n+++ b/provider/translations/en.json\n"
        "@@ -1 +1 @@\n-{}\n+{a}\n"
        "diff --git a/provider/strings.json b/provider/strings.json\n"
        "--- a/provider/strings.json\n+++ b/provider/strings.json\n"
        "@@ -1 +1 @@\n-{}\n+{b}\n"
    )
    out = o._drop_maintainer_owned(patch)
    assert "provider/VERSION" not in out
    assert "provider/translations/en.json" not in out
    # Genuine provider content is kept (strings.json is contributor-owned source):
    assert "provider/config.py" in out
    assert "provider/strings.json" in out


def test_drop_maintainer_owned_noop_when_absent():
    patch = (
        "diff --git a/provider/api.py b/provider/api.py\n"
        "--- a/provider/api.py\n+++ b/provider/api.py\n@@ -1 +1,2 @@\n a\n+b\n"
    )
    assert o._drop_maintainer_owned(patch) == patch


def test_commit_succeeds_without_preexisting_identity(tmp_path, monkeypatch):
    """Regression: a CI clone has no user.name/email; the opener must set its
    own committer identity so `git commit` doesn't fail rc=128 'Author identity
    unknown' (which silently broke every reverse port in production)."""
    import subprocess as sp

    repo = str(tmp_path / "prov")
    real_run = sp.run
    for c in (
        ["git", "-C", tmp_path.as_posix(), "init", "prov"],
        ["git", "-C", repo, "config", "user.email", "seed@example.com"],
        ["git", "-C", repo, "config", "user.name", "Seed"],
    ):
        real_run(c, check=True, capture_output=True)
    (tmp_path / "prov" / "provider").mkdir(parents=True)
    (tmp_path / "prov" / "provider" / "main.py").write_text("x = 1\n")
    real_run(["git", "-C", repo, "add", "-A"], check=True, capture_output=True)
    real_run(
        ["git", "-C", repo, "commit", "-m", "init"], check=True, capture_output=True
    )
    branch = real_run(
        ["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # Remove identity so ONLY the opener's own config can make commit succeed.
    real_run(["git", "-C", repo, "config", "--unset", "user.name"], capture_output=True)
    real_run(
        ["git", "-C", repo, "config", "--unset", "user.email"], capture_output=True
    )

    upstream_patch = (
        "diff --git a/music_assistant/providers/fastmcp_server/main.py "
        "b/music_assistant/providers/fastmcp_server/main.py\n"
        "--- a/music_assistant/providers/fastmcp_server/main.py\n"
        "+++ b/music_assistant/providers/fastmcp_server/main.py\n"
        "@@ -1 +1,2 @@\n x = 1\n+y = 2\n"
    )

    orig_run = o._run  # original wrapper (adds text=True) for git fallthrough

    def fake_run(cmd, **kw):
        if cmd[0] == "gh" and "view" in cmd:
            return sp.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    {"number": 1, "title": "t", "url": "u", "author": {"login": "a"}}
                ),
                "",
            )
        if cmd[0] == "gh" and any("application/vnd.github.diff" in c for c in cmd):
            return sp.CompletedProcess(cmd, 0, upstream_patch, "")
        return orig_run(cmd, **kw)

    monkeypatch.setattr(o, "_run", fake_run)
    # No remote -> push fails. The point: we reach PUSH (commit succeeded),
    # so the error is about push, NOT 'Author identity unknown'.
    with pytest.raises(RuntimeError) as exc:
        o.open_reverse_pr("fastmcp_server", "provider/", "x/y", branch, 1, repo)
    assert "push" in str(exc.value)
    assert "identity" not in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Helpers for _already_present tests
# ---------------------------------------------------------------------------

_DOMAIN = "myprov"
_PROVIDER_PATH = "provider/"
_UP_PATH = f"music_assistant/providers/{_DOMAIN}/api.py"
_PROV_REL = f"{_PROVIDER_PATH}api.py"  # reverse_path result
_UPSTREAM_TEXT = "x = 1\ny = 2\n"

_FAKE_HEAD_JSON = json.dumps(
    {"head": {"repo": {"full_name": "steamEngineer/server"}, "sha": "deadbeef"}}
)
_FAKE_FILES_JSON = json.dumps([{"filename": _UP_PATH, "status": "modified"}])


def _content_json(text: str) -> str:
    """Encode text as a fake GitHub Contents API response body."""
    b64 = base64.b64encode(text.encode()).decode()
    # GitHub chunks base64 at 60 chars with trailing newline.
    chunked = "\n".join(b64[i : i + 60] for i in range(0, len(b64), 60)) + "\n"
    return json.dumps({"content": chunked, "encoding": "base64"})


def _make_fake_run(
    *,
    head_rc: int = 0,
    files_rc: int = 0,
    content_rc: int = 0,
    content_text: str = _UPSTREAM_TEXT,
):
    """Return a fake _run that handles only the _already_present gh calls."""

    def fake_run(cmd, **kw):
        url = cmd[-1] if cmd else ""
        if f"pulls/{42}" in url and "files" not in url:
            return sp.CompletedProcess(
                cmd, head_rc, _FAKE_HEAD_JSON if head_rc == 0 else "", ""
            )
        if f"pulls/{42}/files" in url:
            return sp.CompletedProcess(
                cmd, files_rc, _FAKE_FILES_JSON if files_rc == 0 else "", ""
            )
        if "contents/music_assistant" in url:
            return sp.CompletedProcess(
                cmd,
                content_rc,
                _content_json(content_text) if content_rc == 0 else "",
                "",
            )
        return sp.CompletedProcess(cmd, 1, "", "unhandled")

    return fake_run


# ---------------------------------------------------------------------------
# _already_present unit tests (issue #95)
# ---------------------------------------------------------------------------


def test_already_present_true_when_all_match(tmp_path, monkeypatch):
    """Returns True when every upstream file is in the provider dir with matching content."""
    prov_dir = tmp_path / "repo"
    (prov_dir / _PROVIDER_PATH).mkdir(parents=True)
    (prov_dir / _PROV_REL).write_text(_UPSTREAM_TEXT)

    monkeypatch.setattr(o, "_run", _make_fake_run())

    assert o._already_present(42, _DOMAIN, _PROVIDER_PATH, str(prov_dir)) is True


def test_already_present_false_when_file_differs(tmp_path, monkeypatch):
    """Returns False when the local file content differs from upstream (change not ported)."""
    prov_dir = tmp_path / "repo"
    (prov_dir / _PROVIDER_PATH).mkdir(parents=True)
    (prov_dir / _PROV_REL).write_text("completely different\n")

    monkeypatch.setattr(o, "_run", _make_fake_run())

    assert o._already_present(42, _DOMAIN, _PROVIDER_PATH, str(prov_dir)) is False


def test_already_present_false_when_file_missing(tmp_path, monkeypatch):
    """Returns False when the provider-repo file does not exist."""
    prov_dir = tmp_path / "repo"
    (prov_dir / _PROVIDER_PATH).mkdir(parents=True)
    # Intentionally do NOT create the file.

    monkeypatch.setattr(o, "_run", _make_fake_run())

    assert o._already_present(42, _DOMAIN, _PROVIDER_PATH, str(prov_dir)) is False


def test_already_present_false_when_head_fetch_fails(tmp_path, monkeypatch):
    """Returns False (not an exception) when the first gh call fails."""
    prov_dir = tmp_path / "repo"
    (prov_dir / _PROVIDER_PATH).mkdir(parents=True)
    (prov_dir / _PROV_REL).write_text(_UPSTREAM_TEXT)

    monkeypatch.setattr(o, "_run", _make_fake_run(head_rc=1))

    assert o._already_present(42, _DOMAIN, _PROVIDER_PATH, str(prov_dir)) is False


def test_already_present_false_when_content_fetch_fails(tmp_path, monkeypatch):
    """Returns False when per-file content fetch fails (open PR = safe)."""
    prov_dir = tmp_path / "repo"
    (prov_dir / _PROVIDER_PATH).mkdir(parents=True)
    (prov_dir / _PROV_REL).write_text(_UPSTREAM_TEXT)

    monkeypatch.setattr(o, "_run", _make_fake_run(content_rc=1))

    assert o._already_present(42, _DOMAIN, _PROVIDER_PATH, str(prov_dir)) is False


# ---------------------------------------------------------------------------
# --reject flag test (issue #97)
# ---------------------------------------------------------------------------


def test_apply_command_includes_reject_flag(tmp_path, monkeypatch):
    """The mutable git apply call must include --reject (issue #97).

    With --reject, cleanly-applying hunks land and only conflicting hunks
    drop to .rej files instead of aborting the entire file.  A clean patch
    still returns rc=0, so the test flow reaches push (not apply) failure.
    """
    repo = tmp_path
    for cmd in [
        ["git", "-C", str(repo), "init"],
        ["git", "-C", str(repo), "config", "user.email", "t@t.com"],
        ["git", "-C", str(repo), "config", "user.name", "T"],
    ]:
        sp.run(cmd, check=True, capture_output=True)
    (repo / "provider").mkdir()
    (repo / "provider" / "api.py").write_text("x = 1\n")
    sp.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    sp.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    branch = sp.run(
        ["git", "-C", str(repo), "symbolic-ref", "--short", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    upstream_patch = (
        "diff --git a/music_assistant/providers/myprov/api.py"
        " b/music_assistant/providers/myprov/api.py\n"
        "--- a/music_assistant/providers/myprov/api.py\n"
        "+++ b/music_assistant/providers/myprov/api.py\n"
        "@@ -1 +1,2 @@\n"
        " x = 1\n"
        "+y = 2\n"
    )

    apply_cmds: list[list[str]] = []
    real_run = o._run

    def fake_run(cmd, **kw):
        if cmd[0] == "gh" and "view" in cmd:
            return sp.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    {"number": 5, "title": "T", "url": "U", "author": {"login": "a"}}
                ),
                "",
            )
        if cmd[0] == "gh" and any("application/vnd.github.diff" in c for c in cmd):
            return sp.CompletedProcess(cmd, 0, upstream_patch, "")
        if cmd[0] == "gh":
            # _already_present gh calls → fail → _already_present returns False
            return sp.CompletedProcess(cmd, 1, "", "not authed")
        if "apply" in cmd:
            apply_cmds.append(list(cmd))
        return real_run(cmd, **kw)

    monkeypatch.setattr(o, "_run", fake_run)

    with pytest.raises(RuntimeError, match="push"):
        o.open_reverse_pr("myprov", "provider/", "x/y", branch, 5, str(repo))

    # The mutable apply call (not the echo-dedup probe with --check --reverse)
    # must include --reject.
    mutable = [c for c in apply_cmds if "--check" not in c]
    assert mutable, "no mutable git apply call was recorded"
    assert "--reject" in mutable[0], f"--reject missing from apply cmd: {mutable[0]}"
