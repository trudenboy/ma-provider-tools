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
    monkeypatch.setattr(o, "_fetch_upstream_base", lambda *a, **k: None)

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
    monkeypatch.setattr(o, "_fetch_upstream_base", lambda *a, **k: None)
    # No remote -> push fails. The point: we reach PUSH (commit succeeded),
    # so the error is about push, NOT 'Author identity unknown'.
    with pytest.raises(RuntimeError) as exc:
        o.open_reverse_pr("fastmcp_server", "provider/", "x/y", branch, 1, repo)
    assert "push" in str(exc.value)
    assert "identity" not in str(exc.value).lower()


# ---------------------------------------------------------------------------
# apply flag test (issue #97)
# ---------------------------------------------------------------------------


def test_apply_uses_3way_without_reject(tmp_path, monkeypatch):
    """The mutable git apply call must use --3way and NOT --reject (issue #97).

    git rejects `--3way --reject` together ("cannot be used together"), which
    made every apply fail. --3way alone produces conflict markers for drifted
    hunks. A clean patch still returns rc=0, so the flow reaches push failure.
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
    # must use --3way and must NOT pass --reject (incompatible flags).
    mutable = [c for c in apply_cmds if "--check" not in c]
    assert mutable, "no mutable git apply call was recorded"
    assert "--3way" in mutable[0], f"--3way missing from apply cmd: {mutable[0]}"
    assert "--reject" not in mutable[0], f"--reject must not be combined: {mutable[0]}"


# ---------------------------------------------------------------------------
# content-presence dedup (issue #95) — added-line presence, no network
# ---------------------------------------------------------------------------

_REV_PATCH = (
    "diff --git a/provider/api.py b/provider/api.py\n"
    "--- a/provider/api.py\n+++ b/provider/api.py\n"
    "@@ -1,2 +1,3 @@\n x = 1\n y = 2\n+z = 3\n"
    "diff --git a/tests/test_api.py b/tests/test_api.py\n"
    "--- a/tests/test_api.py\n+++ b/tests/test_api.py\n"
    "@@ -1 +1,2 @@\n a = 1\n+b = 2\n"
)


def test_added_lines_by_file_parses_adds():
    added = o._added_lines_by_file(_REV_PATCH)
    assert added == {"provider/api.py": ["z = 3"], "tests/test_api.py": ["b = 2"]}


def test_already_present_true_when_added_lines_in_files(tmp_path):
    """Drift/snapshot-insensitive: SoT has MORE than the PR base, but every
    added line is present → already ported → skip."""
    (tmp_path / "provider").mkdir()
    # File has the added line plus unrelated later additions (SoT advanced):
    (tmp_path / "provider" / "api.py").write_text("x = 1\ny = 2\nz = 3\nq = 9\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_api.py").write_text("a = 1\nb = 2\nextra = 0\n")
    assert o._already_present(_REV_PATCH, str(tmp_path)) is True


def test_already_present_false_when_added_line_absent(tmp_path):
    (tmp_path / "provider").mkdir()
    (tmp_path / "provider" / "api.py").write_text("x = 1\ny = 2\n")  # missing z=3
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_api.py").write_text("a = 1\nb = 2\n")
    assert o._already_present(_REV_PATCH, str(tmp_path)) is False


def test_already_present_false_when_target_file_missing(tmp_path):
    (tmp_path / "provider").mkdir()
    (tmp_path / "provider" / "api.py").write_text("x = 1\ny = 2\nz = 3\n")
    # tests/test_api.py absent
    assert o._already_present(_REV_PATCH, str(tmp_path)) is False


def test_already_present_false_on_empty_patch(tmp_path):
    assert o._already_present("", str(tmp_path)) is False


def test_already_present_ignores_blank_added_lines(tmp_path):
    """A patch whose only additions are blank lines must NOT be treated as
    already-present-by-coincidence; here a real added line is absent → False."""
    patch = (
        "diff --git a/provider/api.py b/provider/api.py\n"
        "--- a/provider/api.py\n+++ b/provider/api.py\n"
        "@@ -1 +1,3 @@\n x = 1\n+\n+real = 1\n"
    )
    (tmp_path / "provider").mkdir()
    (tmp_path / "provider" / "api.py").write_text("x = 1\n\n")  # blank yes, real no
    assert o._already_present(patch, str(tmp_path)) is False


# ---------------------------------------------------------------------------
# _create_draft_pr labelling (issue #114: needs-human dropped when any label
# is missing in the provider repo — labels must be applied independently)
# ---------------------------------------------------------------------------


def test_create_draft_pr_creates_unlabelled_then_adds_each_label(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return sp.CompletedProcess(cmd, 0, "https://github.com/x/y/pull/9\n", "")

    monkeypatch.setattr(o, "_run", fake_run)
    url = o._create_draft_pr(
        "x/y", "dev", "br", "t", "b", ["reverse-sync", "needs-human"]
    )
    assert url == "https://github.com/x/y/pull/9"
    assert "--label" not in calls[0]  # PR creation never depends on labels
    add_label_calls = [c for c in calls[1:] if "--add-label" in c]
    assert len(add_label_calls) == 2
    assert any("reverse-sync" in c for c in add_label_calls)
    assert any("needs-human" in c for c in add_label_calls)


def test_create_draft_pr_missing_label_created_then_added(monkeypatch):
    calls = []
    failed_once = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "--add-label" in cmd and "needs-human" in cmd and not failed_once:
            failed_once.append(True)
            return sp.CompletedProcess(cmd, 1, "", "'needs-human' not found")
        return sp.CompletedProcess(cmd, 0, "https://github.com/x/y/pull/5\n", "")

    monkeypatch.setattr(o, "_run", fake_run)
    o._create_draft_pr("x/y", "dev", "br", "t", "b", ["needs-human"])
    creates = [c for c in calls if c[:3] == ["gh", "label", "create"]]
    assert len(creates) == 1 and "needs-human" in creates[0]
    retries = [c for c in calls if "--add-label" in c]
    assert len(retries) == 2  # failed add, then retry after label create


def test_create_draft_pr_one_bad_label_does_not_drop_others(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "needs-human" in cmd:
            return sp.CompletedProcess(cmd, 1, "", "boom")
        return sp.CompletedProcess(cmd, 0, "https://github.com/x/y/pull/5\n", "")

    monkeypatch.setattr(o, "_run", fake_run)
    url = o._create_draft_pr(
        "x/y", "dev", "br", "t", "b", ["needs-human", "reverse-sync"]
    )
    assert url == "https://github.com/x/y/pull/5"  # PR survives label failure
    ok_adds = [c for c in calls if "--add-label" in c and "reverse-sync" in c]
    assert len(ok_adds) == 1  # the other label is still applied


def test_create_draft_pr_raises_when_create_fails(monkeypatch):
    monkeypatch.setattr(
        o, "_run", lambda cmd, **kw: sp.CompletedProcess(cmd, 1, "", "boom")
    )
    with pytest.raises(RuntimeError, match="gh pr create failed"):
        o._create_draft_pr("x/y", "dev", "br", "t", "b", ["reverse-sync"])


# ---------------------------------------------------------------------------
# _fetch_upstream_base — enable real --3way via base blobs (issue #97)
# ---------------------------------------------------------------------------


def test_fetch_upstream_base_issues_readonly_commands(monkeypatch):
    cmds = []

    def fake_run(cmd, **kw):
        cmds.append(cmd)
        if cmd[:2] == ["gh", "api"]:
            return sp.CompletedProcess(cmd, 0, "cfd9843\n", "")
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(o, "_run", fake_run)
    o._fetch_upstream_base("/tmp/x", 4313)

    assert cmds[0][:2] == ["gh", "api"]
    assert "repos/music-assistant/server/pulls/4313" in cmds[0]
    assert any(c[:4] == ["git", "-C", "/tmp/x", "remote"] for c in cmds)
    fetch = [c for c in cmds if "fetch" in c][0]
    assert fetch[-2:] == ["upstream", "cfd9843"]  # fetches the base sha, read-only
    # No write verb to upstream anywhere (push/pr/issue).
    assert not any("push" in c for c in cmds)


def test_fetch_upstream_base_swallows_failure(monkeypatch):
    def boom(cmd, **kw):
        return sp.CompletedProcess(cmd, 1, "", "no auth")  # gh api base.sha empty

    monkeypatch.setattr(o, "_run", boom)
    # Must not raise — best-effort; apply proceeds without the base blobs.
    o._fetch_upstream_base("/tmp/x", 4313)
