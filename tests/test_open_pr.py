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

CLEAN_APPLY = o.PatchApplyResult(
    (o.FileApplyResult("provider/api.py", "applied", "three_way", (), ""),)
)
CONFLICT_APPLY = o.PatchApplyResult(
    (
        o.FileApplyResult("provider/api.py", "applied", "three_way", (), ""),
        o.FileApplyResult(
            "tests/test_api.py",
            "conflicted",
            "three_way",
            ("tests/test_api.py",),
            "diff3 overlap",
        ),
    )
)


def test_build_branch():
    assert (
        o.build_branch("fastmcp_server", 4313) == "reverse-sync/fastmcp_server-pr4313"
    )


def test_body_has_upstream_link_and_credit():
    body = o.build_pr_body(PR, "fastmcp_server", CLEAN_APPLY)
    assert "music-assistant/server/pull/4313" in body
    assert "@alice" in body
    assert "VERSION" in body  # reminder line about maintainer-owned files


def test_body_flags_conflicts():
    clean = o.build_pr_body(PR, "fastmcp_server", CLEAN_APPLY)
    dirty = o.build_pr_body(PR, "fastmcp_server", CONFLICT_APPLY)
    assert "conflict" in dirty.lower()
    assert "conflict" not in clean.lower()
    assert "tests/test_api.py" in dirty
    assert "provider/api.py" not in dirty


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
    monkeypatch.setattr(o, "_fetch_upstream_commits", lambda *a, **k: ("base", "head"))
    monkeypatch.setattr(
        o,
        "_load_snapshot_sections",
        lambda *args: (
            o.SnapshotSection(
                "provider/main.py",
                "provider/main.py",
                o.FileSnapshot(b"# content\n", "100644"),
                o.FileSnapshot(b"# content\n# new line\n", "100644"),
            ),
        ),
    )
    monkeypatch.setattr(o, "_find_existing_reverse_pr", lambda *a, **k: None)
    monkeypatch.setattr(o, "_remote_branch_sha", lambda *a, **k: None)

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


def test_drop_maintainer_owned_rejects_rename_from_owned_source():
    patch = (
        "diff --git a/VERSION b/provider/version.py\n"
        "similarity index 100%\n"
        "rename from VERSION\n"
        "rename to provider/version.py\n"
    )

    assert o._drop_maintainer_owned(patch) == ""


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
    monkeypatch.setattr(o, "_fetch_upstream_commits", lambda *a, **k: ("base", "head"))
    monkeypatch.setattr(
        o,
        "_load_snapshot_sections",
        lambda *args: (
            o.SnapshotSection(
                "provider/main.py",
                "provider/main.py",
                o.FileSnapshot(b"x = 1\n", "100644"),
                o.FileSnapshot(b"x = 1\ny = 2\n", "100644"),
            ),
        ),
    )
    monkeypatch.setattr(o, "_find_existing_reverse_pr", lambda *a, **k: None)
    monkeypatch.setattr(o, "_remote_branch_sha", lambda *a, **k: None)
    # No remote -> push fails. The point: we reach PUSH (commit succeeded),
    # so the error is about push, NOT 'Author identity unknown'.
    with pytest.raises(RuntimeError) as exc:
        o.open_reverse_pr("fastmcp_server", "provider/", "x/y", branch, 1, repo)
    assert "push" in str(exc.value)
    assert "identity" not in str(exc.value).lower()


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
    result = o._create_draft_pr(
        "x/y", "dev", "br", "t", "b", ["reverse-sync", "needs-human"]
    )
    assert result == o.DraftPrResult("https://github.com/x/y/pull/9", False, ())
    assert "--label" not in calls[0]  # PR creation never depends on labels
    add_label_calls = [c for c in calls[1:] if "repos/x/y/issues/9/labels" in c]
    assert len(add_label_calls) == 2
    assert any("labels[]=reverse-sync" in c for c in add_label_calls)
    assert any("labels[]=needs-human" in c for c in add_label_calls)
    assert all(c[:2] == ["gh", "api"] for c in add_label_calls)


def test_create_draft_pr_missing_label_created_then_added(monkeypatch):
    calls = []
    failed_once = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "labels[]=needs-human" in cmd and not failed_once:
            failed_once.append(True)
            return sp.CompletedProcess(cmd, 1, "", "'needs-human' not found")
        if "repos/x/y/labels/needs-human" in cmd:
            return sp.CompletedProcess(cmd, 1, "", "HTTP 404 Not Found")
        return sp.CompletedProcess(cmd, 0, "https://github.com/x/y/pull/5\n", "")

    monkeypatch.setattr(o, "_run", fake_run)
    o._create_draft_pr("x/y", "dev", "br", "t", "b", ["needs-human"])
    creates = [c for c in calls if "repos/x/y/labels" in c]
    assert len(creates) == 1 and "name=needs-human" in creates[0]
    retries = [c for c in calls if "repos/x/y/issues/5/labels" in c]
    assert len(retries) == 2  # failed add, then retry after label create


def test_create_draft_pr_one_bad_label_does_not_drop_others(monkeypatch):
    calls = []
    needs_human_adds = 0

    def fake_run(cmd, **kw):
        nonlocal needs_human_adds
        calls.append(cmd)
        joined = " ".join(cmd)
        if "labels[]=needs-human" in joined:
            needs_human_adds += 1
            if needs_human_adds == 1:
                return sp.CompletedProcess(cmd, 1, "", "label not found")
            return sp.CompletedProcess(cmd, 1, "", "boom")
        if "repos/x/y/labels/needs-human" in joined:
            return sp.CompletedProcess(cmd, 1, "", "HTTP 404 Not Found")
        if "name=needs-human" in joined:
            return sp.CompletedProcess(cmd, 1, "", "boom")
        return sp.CompletedProcess(cmd, 0, "https://github.com/x/y/pull/5\n", "")

    monkeypatch.setattr(o, "_run", fake_run)
    result = o._create_draft_pr(
        "x/y", "dev", "br", "t", "b", ["needs-human", "reverse-sync"]
    )
    assert result.url == "https://github.com/x/y/pull/5"  # PR survives label failure
    assert result.label_failures == (
        o.LabelFailure(
            "needs-human", "add: label not found; create: boom; retry: boom"
        ),
    )
    ok_adds = [
        c
        for c in calls
        if "repos/x/y/issues/5/labels" in c and "labels[]=reverse-sync" in c
    ]
    assert len(ok_adds) == 1  # the other label is still applied


def test_add_label_non_missing_failure_does_not_try_to_create(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return sp.CompletedProcess(cmd, 1, "", "HTTP 403 forbidden")

    monkeypatch.setattr(o, "_run", fake_run)

    assert o._add_label("x/y", 5, "reverse-sync") == o.LabelFailure(
        "reverse-sync", "add: HTTP 403 forbidden; lookup: HTTP 403 forbidden"
    )
    assert len(calls) == 2
    assert "repos/x/y/issues/5/labels" in calls[0]
    assert "repos/x/y/labels/reverse-sync" in calls[1]


def test_create_draft_pr_raises_when_create_fails(monkeypatch):
    monkeypatch.setattr(
        o, "_run", lambda cmd, **kw: sp.CompletedProcess(cmd, 1, "", "boom")
    )
    with pytest.raises(RuntimeError, match="gh pr create failed"):
        o._create_draft_pr("x/y", "dev", "br", "t", "b", ["reverse-sync"])


def _safe_existing_pr() -> dict:
    return {
        "number": 278,
        "html_url": "https://github.com/x/y/pull/278",
        "draft": True,
        "base": {"ref": "dev"},
        "head": {
            "ref": "reverse-sync/fastmcp_server-pr5782",
            "sha": "a" * 40,
        },
    }


def test_find_existing_reverse_pr_accepts_only_bot_scaffold(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        endpoint = cmd[2]
        if endpoint == "repos/x/y/pulls":
            return sp.CompletedProcess(cmd, 0, json.dumps([_safe_existing_pr()]), "")
        if endpoint.endswith("/commits"):
            return sp.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    [
                        {
                            "author": {"login": "github-actions[bot]"},
                            "commit": {
                                "message": "reverse-sync: port music-assistant/server#5782\n\ntrailer"
                            },
                        }
                    ]
                ),
                "",
            )
        if endpoint.endswith("/files"):
            return sp.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    [
                        {"filename": "CHANGELOG.md"},
                        {"filename": "specs/inprogress/reverse-sync-pr5782.md"},
                    ]
                ),
                "",
            )
        raise AssertionError(cmd)

    monkeypatch.setattr(o, "_run", fake_run)

    existing = o._find_existing_reverse_pr(
        "x/y", "dev", "reverse-sync/fastmcp_server-pr5782", 5782
    )

    assert existing == _safe_existing_pr()
    assert calls[0][:3] == ["gh", "api", "repos/x/y/pulls"]
    assert "--method" in calls[0] and "GET" in calls[0]


@pytest.mark.parametrize("unsafe", ["extra_commit", "provider_file"])
def test_find_existing_reverse_pr_refuses_human_changes(monkeypatch, unsafe):
    def fake_run(cmd, **kwargs):
        endpoint = cmd[2]
        if endpoint == "repos/x/y/pulls":
            return sp.CompletedProcess(cmd, 0, json.dumps([_safe_existing_pr()]), "")
        if endpoint.endswith("/commits"):
            commits = [
                {
                    "author": {"login": "github-actions[bot]"},
                    "commit": {
                        "message": "reverse-sync: port music-assistant/server#5782"
                    },
                }
            ]
            if unsafe == "extra_commit":
                commits.append(
                    {
                        "author": {"login": "alice"},
                        "commit": {"message": "resolve conflict"},
                    }
                )
            return sp.CompletedProcess(cmd, 0, json.dumps(commits), "")
        files = [{"filename": "CHANGELOG.md"}]
        if unsafe == "provider_file":
            files.append({"filename": "provider/api.py"})
        return sp.CompletedProcess(cmd, 0, json.dumps(files), "")

    monkeypatch.setattr(o, "_run", fake_run)

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        o._find_existing_reverse_pr(
            "x/y", "dev", "reverse-sync/fastmcp_server-pr5782", 5782
        )


def test_remote_branch_without_open_pr_is_never_overwritten(monkeypatch):
    monkeypatch.setattr(o, "_remote_branch_sha", lambda *args: "b" * 40)

    with pytest.raises(RuntimeError, match="remote branch exists without a verified"):
        o._verify_remote_branch_ownership(
            "/tmp/provider", "reverse-sync/fastmcp_server-pr5782", None
        )


def test_verified_pr_requires_matching_remote_head(monkeypatch):
    monkeypatch.setattr(o, "_remote_branch_sha", lambda *args: "b" * 40)

    with pytest.raises(RuntimeError, match="remote branch moved"):
        o._verify_remote_branch_ownership(
            "/tmp/provider",
            "reverse-sync/fastmcp_server-pr5782",
            _safe_existing_pr(),
        )


@pytest.mark.parametrize(
    ("existing", "expected_push"),
    [
        (None, ["push", "-u", "origin", "reverse-sync/test-pr138"]),
        (
            _safe_existing_pr(),
            [
                "push",
                "-u",
                "--force-with-lease=refs/heads/reverse-sync/test-pr138:" + "a" * 40,
                "origin",
                "reverse-sync/test-pr138",
            ],
        ),
    ],
)
def test_branch_push_is_create_only_or_sha_leased(monkeypatch, existing, expected_push):
    calls: list[tuple] = []
    monkeypatch.setattr(o, "_git_mut", lambda *args: calls.append(args))

    o._push_reverse_branch("/tmp/provider", "reverse-sync/test-pr138", existing)

    assert calls == [("/tmp/provider", *expected_push)]


def test_create_draft_pr_updates_safe_existing_pr_and_preserves_number(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "api", "repos/x/y/pulls/278"]:
            return sp.CompletedProcess(
                cmd, 0, json.dumps({"html_url": _safe_existing_pr()["html_url"]}), ""
            )
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(o, "_run", fake_run)

    result = o._create_draft_pr(
        "x/y",
        "dev",
        "reverse-sync/fastmcp_server-pr5782",
        "title",
        "body",
        ["reverse-sync"],
        existing=_safe_existing_pr(),
    )

    assert result == o.DraftPrResult("https://github.com/x/y/pull/278", True, ())
    patch_calls = [c for c in calls if "PATCH" in c]
    assert len(patch_calls) == 1
    assert "repos/x/y/pulls/278" in patch_calls[0]
    assert not any(c[:3] == ["gh", "pr", "create"] for c in calls)
    assert any("repos/x/y/issues/278/labels" in c for c in calls)


def test_reused_clean_pr_removes_stale_needs_human_label(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "api", "repos/x/y/pulls/278"]:
            return sp.CompletedProcess(
                cmd, 0, json.dumps({"html_url": _safe_existing_pr()["html_url"]}), ""
            )
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(o, "_run", fake_run)

    result = o._create_draft_pr(
        "x/y",
        "dev",
        "reverse-sync/fastmcp_server-pr5782",
        "title",
        "body",
        ["reverse-sync"],
        existing=_safe_existing_pr(),
    )

    assert result.label_failures == ()
    delete = [
        call for call in calls if "repos/x/y/issues/278/labels/needs-human" in call
    ]
    assert len(delete) == 1
    assert "DELETE" in delete[0]


def test_add_label_does_not_create_for_unrelated_validation_failure(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "repos/x/y/issues/5/labels" in cmd:
            return sp.CompletedProcess(cmd, 1, "", "HTTP 422 validation failed")
        if "repos/x/y/labels/reverse-sync" in cmd:
            return sp.CompletedProcess(cmd, 0, "{}", "")
        raise AssertionError(cmd)

    monkeypatch.setattr(o, "_run", fake_run)

    failure = o._add_label("x/y", 5, "reverse-sync")

    assert failure == o.LabelFailure("reverse-sync", "HTTP 422 validation failed")
    assert not any("name=reverse-sync" in call for call in calls)


def test_provider_pr_writes_never_target_upstream(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "create"]:
            return sp.CompletedProcess(cmd, 0, "https://github.com/x/y/pull/9\n", "")
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(o, "_run", fake_run)
    o._create_draft_pr("x/y", "dev", "br", "t", "b", ["reverse-sync"])

    writes = [c for c in calls if "POST" in c or "PATCH" in c or "create" in c]
    assert writes
    assert all("music-assistant/" not in " ".join(command) for command in writes)


# ---------------------------------------------------------------------------
# _fetch_upstream_commits — provide normalized base/head snapshots
# ---------------------------------------------------------------------------


def test_fetch_upstream_commits_issues_readonly_commands(monkeypatch):
    cmds = []

    def fake_run(cmd, **kw):
        cmds.append(cmd)
        if cmd[:2] == ["gh", "api"]:
            return sp.CompletedProcess(cmd, 0, "base123\thead456\n", "")
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(o, "_run", fake_run)
    assert o._fetch_upstream_commits("/tmp/x", 4313) == ("base123", "head456")

    assert cmds[0][:2] == ["gh", "api"]
    assert "repos/music-assistant/server/pulls/4313" in cmds[0]
    assert any(c[:4] == ["git", "-C", "/tmp/x", "remote"] for c in cmds)
    fetches = [c for c in cmds if "fetch" in c]
    assert [c[-1] for c in fetches] == ["base123", "head456"]
    # No write verb to upstream anywhere (push/pr/issue).
    assert not any("push" in c for c in cmds)


def test_fetch_upstream_commits_fails_when_snapshots_cannot_be_loaded(monkeypatch):
    def boom(cmd, **kw):
        return sp.CompletedProcess(cmd, 1, "", "no auth")

    monkeypatch.setattr(o, "_run", boom)
    with pytest.raises(RuntimeError, match="upstream snapshot lookup.*no auth"):
        o._fetch_upstream_commits("/tmp/x", 4313)


def test_conflicted_pr_title_has_durable_needs_human_prefix():
    assert o._build_pr_title(PR, CONFLICT_APPLY) == (
        "[needs-human] reverse-sync: Fix track parsing (#4313)"
    )


# ---------------------------------------------------------------------------
# Per-file apply integrity (issue #138)
# ---------------------------------------------------------------------------


def _init_provider_repo(path: Path, files: dict[str, str]) -> str:
    repo = str(path)
    sp.run(["git", "-C", repo, "init"], check=True, capture_output=True)
    sp.run(
        ["git", "-C", repo, "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    sp.run(
        ["git", "-C", repo, "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    for rel, content in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    sp.run(["git", "-C", repo, "add", "-A"], check=True, capture_output=True)
    sp.run(
        ["git", "-C", repo, "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    return repo


def test_snapshot_merge_replaces_unchanged_base_with_upstream_head(tmp_path):
    """Changing the base comparison must prevent a clean incoming update."""
    repo = _init_provider_repo(tmp_path, {"provider/api.py": "old = 1\n"})
    section = o.SnapshotSection(
        source_path="provider/api.py",
        target_path="provider/api.py",
        base=o.FileSnapshot(b"old = 1\n", "100644"),
        incoming=o.FileSnapshot(b"new = 1\n", "100644"),
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result == o.PatchApplyResult(
        (o.FileApplyResult("provider/api.py", "applied", "three_way", (), ""),)
    )
    assert (tmp_path / "provider/api.py").read_text() == "new = 1\n"


def test_snapshot_merge_classifies_matching_head_as_already_present(tmp_path):
    repo = _init_provider_repo(tmp_path, {"provider/api.py": "new = 1\n"})
    section = o.SnapshotSection(
        source_path="provider/api.py",
        target_path="provider/api.py",
        base=o.FileSnapshot(b"old = 1\n", "100644"),
        incoming=o.FileSnapshot(b"new = 1\n", "100644"),
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.already_present_paths == ["provider/api.py"]
    assert o._changed_paths(repo) == set()


def test_snapshot_merge_preserves_independent_provider_changes(tmp_path):
    base = b"provider = 1\nkeep_1\nkeep_2\nkeep_3\nkeep_4\nupstream = 1\n"
    repo = _init_provider_repo(
        tmp_path,
        {
            "provider/api.py": (
                "provider = 2\nkeep_1\nkeep_2\nkeep_3\nkeep_4\nupstream = 1\n"
            )
        },
    )
    section = o.SnapshotSection(
        source_path="provider/api.py",
        target_path="provider/api.py",
        base=o.FileSnapshot(base, "100644"),
        incoming=o.FileSnapshot(
            b"provider = 1\nkeep_1\nkeep_2\nkeep_3\nkeep_4\nupstream = 2\n",
            "100644",
        ),
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.applied_paths == ["provider/api.py"]
    assert result.conflicts is False
    assert (tmp_path / "provider/api.py").read_text() == (
        "provider = 2\nkeep_1\nkeep_2\nkeep_3\nkeep_4\nupstream = 2\n"
    )


def test_snapshot_merge_deduplicates_head_change_with_provider_drift(tmp_path):
    repo = _init_provider_repo(
        tmp_path,
        {
            "provider/api.py": (
                "provider = 2\nkeep_1\nkeep_2\nkeep_3\nkeep_4\nupstream = 2\n"
            )
        },
    )
    section = o.SnapshotSection(
        "provider/api.py",
        "provider/api.py",
        o.FileSnapshot(
            b"provider = 1\nkeep_1\nkeep_2\nkeep_3\nkeep_4\nupstream = 1\n",
            "100644",
        ),
        o.FileSnapshot(
            b"provider = 1\nkeep_1\nkeep_2\nkeep_3\nkeep_4\nupstream = 2\n",
            "100644",
        ),
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.already_present_paths == ["provider/api.py"]
    assert o._changed_paths(repo) == set()


def test_snapshot_merge_writes_real_diff3_markers_for_overlap(tmp_path):
    repo = _init_provider_repo(tmp_path, {"provider/api.py": "value = 'provider'\n"})
    section = o.SnapshotSection(
        source_path="provider/api.py",
        target_path="provider/api.py",
        base=o.FileSnapshot(b"value = 'base'\n", "100644"),
        incoming=o.FileSnapshot(b"value = 'upstream'\n", "100644"),
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.conflicted_paths == ["provider/api.py"]
    assert result.files[0].artifacts == ("provider/api.py",)
    merged = (tmp_path / "provider/api.py").read_text()
    assert "<<<<<<< provider" in merged
    assert "||||||| upstream-base" in merged
    assert ">>>>>>> upstream-head" in merged


def test_snapshot_merge_accepts_multiple_diff3_conflict_regions(tmp_path):
    base_lines = [f"line {index}\n" for index in range(20)]
    provider_lines = list(base_lines)
    incoming_lines = list(base_lines)
    provider_lines[1] = "provider one\n"
    provider_lines[18] = "provider two\n"
    incoming_lines[1] = "upstream one\n"
    incoming_lines[18] = "upstream two\n"
    repo = _init_provider_repo(tmp_path, {"provider/api.py": "".join(provider_lines)})
    section = o.SnapshotSection(
        "provider/api.py",
        "provider/api.py",
        o.FileSnapshot("".join(base_lines).encode(), "100644"),
        o.FileSnapshot("".join(incoming_lines).encode(), "100644"),
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.conflicted_paths == ["provider/api.py"]
    assert (tmp_path / "provider/api.py").read_text().count("<<<<<<< provider") == 2


def test_snapshot_merge_materializes_touched_file_missing_from_provider(tmp_path):
    """Regression for #5782: an unsynced test still receives the head snapshot."""
    repo = _init_provider_repo(tmp_path, {"README.md": "provider\n"})
    section = o.SnapshotSection(
        source_path="tests/test_debug.py",
        target_path="tests/test_debug.py",
        base=o.FileSnapshot(b"for i in range(10):\n", "100644"),
        incoming=o.FileSnapshot(b"for _ in range(10):\n", "100644"),
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.applied_paths == ["tests/test_debug.py"]
    assert (tmp_path / "tests/test_debug.py").read_text() == "for _ in range(10):\n"


def test_snapshot_sections_load_and_reverse_transform_base_and_head(tmp_path):
    repo = _init_provider_repo(
        tmp_path,
        {
            "tests/providers/demo/test_debug.py": (
                "from music_assistant.providers.demo.debug import dump\n"
                "for i in range(10):\n"
            )
        },
    )
    base_sha = sp.run(
        ["git", "-C", repo, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    target = tmp_path / "tests/providers/demo/test_debug.py"
    target.write_text(
        "from music_assistant.providers.demo.debug import dump\nfor _ in range(10):\n"
    )
    sp.run(["git", "-C", repo, "add", "-A"], check=True, capture_output=True)
    sp.run(
        ["git", "-C", repo, "commit", "-m", "head"],
        check=True,
        capture_output=True,
    )
    head_sha = sp.run(
        ["git", "-C", repo, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    patch_section = o.PatchSection(
        "tests/test_debug.py", "tests/test_debug.py", "unused"
    )

    snapshots = o._load_snapshot_sections(
        (patch_section,), repo, base_sha, head_sha, "demo", "provider/"
    )

    assert snapshots == (
        o.SnapshotSection(
            source_path="tests/test_debug.py",
            target_path="tests/test_debug.py",
            base=o.FileSnapshot(
                b"from provider.debug import dump\nfor i in range(10):\n", "100644"
            ),
            incoming=o.FileSnapshot(
                b"from provider.debug import dump\nfor _ in range(10):\n", "100644"
            ),
        ),
    )


def test_snapshot_loader_fails_closed_when_modified_base_is_missing(
    tmp_path, monkeypatch
):
    section = o.PatchSection(
        "provider/api.py",
        "provider/api.py",
        (
            "diff --git a/provider/api.py b/provider/api.py\n"
            "--- a/provider/api.py\n+++ b/provider/api.py\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        ),
    )
    monkeypatch.setattr(
        o,
        "_snapshot_at_commit",
        lambda provider_dir, commit, *args: (
            None if commit == "base" else o.FileSnapshot(b"new\n", "100644")
        ),
    )

    with pytest.raises(RuntimeError, match="modify.*requires BASE and HEAD"):
        o._load_snapshot_sections(
            (section,), str(tmp_path), "base", "head", "demo", "provider/"
        )


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ("new file mode 100644\n", "add"),
        ("deleted file mode 100644\n", "delete"),
        ("similarity index 100%\nrename from provider/a.py\n", "rename"),
        ("similarity index 100%\ncopy from provider/a.py\n", "copy"),
        ("index 1111111..2222222 100644\n", "modify"),
    ],
)
def test_patch_operation_classifies_diff_metadata(metadata, expected):
    section = o.PatchSection(
        "provider/b.py",
        "provider/a.py",
        "diff --git a/provider/a.py b/provider/b.py\n" + metadata,
    )

    assert o._patch_operation(section) == expected


def test_snapshot_merge_keeps_clean_file_when_another_file_conflicts(tmp_path):
    repo = _init_provider_repo(
        tmp_path,
        {
            "provider/clean.py": "old = 1\n",
            "provider/drifted.py": "value = 'provider'\n",
        },
    )
    sections = (
        o.SnapshotSection(
            "provider/clean.py",
            "provider/clean.py",
            o.FileSnapshot(b"old = 1\n", "100644"),
            o.FileSnapshot(b"new = 1\n", "100644"),
        ),
        o.SnapshotSection(
            "provider/drifted.py",
            "provider/drifted.py",
            o.FileSnapshot(b"value = 'base'\n", "100644"),
            o.FileSnapshot(b"value = 'upstream'\n", "100644"),
        ),
    )

    result = o._merge_snapshot_sections(sections, repo)

    assert result.applied_paths == ["provider/clean.py"]
    assert result.conflicted_paths == ["provider/drifted.py"]
    assert (tmp_path / "provider/clean.py").read_text() == "new = 1\n"
    assert "<<<<<<< provider" in (tmp_path / "provider/drifted.py").read_text()


def test_snapshot_merge_applies_mode_only_change(tmp_path):
    repo = _init_provider_repo(tmp_path, {"scripts/tool.sh": "#!/bin/sh\n"})
    section = o.SnapshotSection(
        "scripts/tool.sh",
        "scripts/tool.sh",
        o.FileSnapshot(b"#!/bin/sh\n", "100644"),
        o.FileSnapshot(b"#!/bin/sh\n", "100755"),
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.applied_paths == ["scripts/tool.sh"]
    assert (tmp_path / "scripts/tool.sh").stat().st_mode & 0o111


def test_snapshot_merge_applies_delete_and_rename(tmp_path):
    repo = _init_provider_repo(
        tmp_path,
        {"provider/delete.py": "gone\n", "provider/old.py": "renamed\n"},
    )
    sections = (
        o.SnapshotSection(
            "provider/delete.py",
            "provider/delete.py",
            o.FileSnapshot(b"gone\n", "100644"),
            None,
            operation="delete",
        ),
        o.SnapshotSection(
            "provider/old.py",
            "provider/new.py",
            o.FileSnapshot(b"renamed\n", "100644"),
            o.FileSnapshot(b"renamed\n", "100644"),
            remove_source=True,
            operation="rename",
        ),
    )

    result = o._merge_snapshot_sections(sections, repo)

    assert result.applied_paths == ["provider/delete.py", "provider/new.py"]
    assert not (tmp_path / "provider/delete.py").exists()
    assert not (tmp_path / "provider/old.py").exists()
    assert (tmp_path / "provider/new.py").read_text() == "renamed\n"


def test_snapshot_merge_applies_copy_without_removing_source(tmp_path):
    repo = _init_provider_repo(tmp_path, {"provider/source.py": "copied\n"})
    section = o.SnapshotSection(
        "provider/source.py",
        "provider/copy.py",
        o.FileSnapshot(b"copied\n", "100644"),
        o.FileSnapshot(b"copied\n", "100644"),
        remove_source=False,
        operation="copy",
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.applied_paths == ["provider/copy.py"]
    assert (tmp_path / "provider/source.py").read_text() == "copied\n"
    assert (tmp_path / "provider/copy.py").read_text() == "copied\n"


@pytest.mark.parametrize(
    ("operation", "remove_source"), [("rename", True), ("copy", False)]
)
def test_snapshot_merge_does_not_dedup_pending_path_operation(
    tmp_path, operation, remove_source
):
    repo = _init_provider_repo(tmp_path, {"provider/source.py": "head content\n"})
    section = o.SnapshotSection(
        "provider/source.py",
        "provider/target.py",
        o.FileSnapshot(b"base content\n", "100644"),
        o.FileSnapshot(b"head content\n", "100644"),
        remove_source=remove_source,
        operation=operation,
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.applied_paths == ["provider/target.py"]
    assert (tmp_path / "provider/target.py").read_text() == "head content\n"
    assert (tmp_path / "provider/source.py").exists() is (not remove_source)


def test_snapshot_merge_recognizes_already_applied_rename(tmp_path):
    repo = _init_provider_repo(tmp_path, {"provider/new.py": "renamed\n"})
    section = o.SnapshotSection(
        "provider/old.py",
        "provider/new.py",
        o.FileSnapshot(b"old\n", "100644"),
        o.FileSnapshot(b"renamed\n", "100644"),
        remove_source=True,
        operation="rename",
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.already_present_paths == ["provider/new.py"]
    assert o._changed_paths(repo) == set()


def test_snapshot_merge_marks_modify_delete_as_structural_conflict(tmp_path):
    repo = _init_provider_repo(tmp_path, {"provider/api.py": "provider edit\n"})
    section = o.SnapshotSection(
        "provider/api.py",
        "provider/api.py",
        o.FileSnapshot(b"base\n", "100644"),
        None,
        operation="delete",
    )

    result = o._merge_snapshot_sections((section,), repo)

    assert result.conflicted_paths == ["provider/api.py"]
    merged = (tmp_path / "provider/api.py").read_text()
    assert "<<<<<<< provider\nprovider edit\n" in merged
    assert "||||||| upstream-base\nbase\n" in merged
    assert "=======\n<deleted by upstream>\n" in merged


@pytest.mark.parametrize("unexpected", [False, True])
def test_snapshot_postcondition_rejects_missing_outcome_or_unexpected_path(unexpected):
    snapshot = o.FileSnapshot(b"x\n", "100644")
    sections = (
        o.SnapshotSection("provider/api.py", "provider/api.py", snapshot, snapshot),
        o.SnapshotSection("tests/test_api.py", "tests/test_api.py", snapshot, snapshot),
    )
    files = (o.FileApplyResult("provider/api.py", "applied", "three_way", (), ""),)
    changed = {"provider/api.py"}
    if unexpected:
        files += (
            o.FileApplyResult("tests/test_api.py", "applied", "three_way", (), ""),
        )
        changed.add("unrelated.txt")

    with pytest.raises(RuntimeError, match="postcondition"):
        o._validate_merge_postcondition(sections, o.PatchApplyResult(files), changed)


def test_snapshot_postcondition_rejects_applied_result_without_changed_file():
    snapshot = o.FileSnapshot(b"x\n", "100644")
    sections = (
        o.SnapshotSection("provider/api.py", "provider/api.py", snapshot, snapshot),
    )
    result = o.PatchApplyResult(
        (o.FileApplyResult("provider/api.py", "applied", "three_way", (), ""),)
    )

    with pytest.raises(RuntimeError, match="no_changed_path"):
        o._validate_merge_postcondition(sections, result, set())


def _mock_upstream_pr(monkeypatch, patch: str, writes: list[list[str]]) -> None:
    real_run = o._run

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["gh", "pr"] and "view" in cmd:
            return sp.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    {
                        "number": 138,
                        "title": "Apply integrity",
                        "url": "https://github.com/music-assistant/server/pull/138",
                        "author": {"login": "alice"},
                    }
                ),
                "",
            )
        if cmd[:2] == ["gh", "api"] and any(
            "application/vnd.github.diff" in item for item in cmd
        ):
            return sp.CompletedProcess(cmd, 0, patch, "")
        if cmd[:3] == ["git", "-C", str(cmd[2])] and "push" in cmd:
            writes.append(cmd)
        if cmd[:3] == ["gh", "pr", "create"]:
            writes.append(cmd)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(o, "_run", fake_run)
    monkeypatch.setattr(o, "_fetch_upstream_commits", lambda *args: ("base", "head"))
    monkeypatch.setattr(o, "_find_existing_reverse_pr", lambda *args: None)
    monkeypatch.setattr(o, "_remote_branch_sha", lambda *args: None)


def test_open_reverse_pr_skips_when_every_section_is_already_present(
    tmp_path, monkeypatch
):
    repo = _init_provider_repo(tmp_path, {"provider/api.py": "old = 1\nnew = 1\n"})
    branch = sp.run(
        ["git", "-C", repo, "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    patch = (
        "diff --git a/music_assistant/providers/test/api.py "
        "b/music_assistant/providers/test/api.py\n"
        "--- a/music_assistant/providers/test/api.py\n"
        "+++ b/music_assistant/providers/test/api.py\n"
        "@@ -1 +1,2 @@\n old = 1\n+new = 1\n"
    )
    writes: list[list[str]] = []
    _mock_upstream_pr(monkeypatch, patch, writes)
    monkeypatch.setattr(
        o,
        "_load_snapshot_sections",
        lambda *args: (
            o.SnapshotSection(
                "provider/api.py",
                "provider/api.py",
                o.FileSnapshot(b"old = 1\n", "100644"),
                o.FileSnapshot(b"old = 1\nnew = 1\n", "100644"),
            ),
        ),
    )

    result = o.open_reverse_pr("test", "provider/", "owner/repo", branch, 138, repo)

    assert result == {
        "skipped": True,
        "reason": "already present (all sections)",
        "pr_url": None,
        "conflicts": False,
        "reused": False,
        "applied_paths": [],
        "conflicted_paths": [],
        "label_failures": [],
    }
    assert writes == []


def test_open_reverse_pr_apply_failure_stops_before_scaffold_or_external_write(
    tmp_path, monkeypatch
):
    repo = _init_provider_repo(tmp_path, {"provider/api.py": "old = 1\n"})
    branch = sp.run(
        ["git", "-C", repo, "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    patch = (
        "diff --git a/music_assistant/providers/test/api.py "
        "b/music_assistant/providers/test/api.py\n"
        "--- a/music_assistant/providers/test/api.py\n"
        "+++ b/music_assistant/providers/test/api.py\n"
        "@@ -1 +1 @@\n-old = 1\n+new = 1\n"
    )
    writes: list[list[str]] = []
    _mock_upstream_pr(monkeypatch, patch, writes)
    snapshots = (
        o.SnapshotSection(
            "provider/api.py",
            "provider/api.py",
            o.FileSnapshot(b"old = 1\n", "100644"),
            o.FileSnapshot(b"new = 1\n", "100644"),
        ),
    )
    monkeypatch.setattr(o, "_load_snapshot_sections", lambda *args: snapshots)
    monkeypatch.setattr(
        o,
        "_merge_snapshot_sections",
        lambda *args: (_ for _ in ()).throw(RuntimeError("integrity failure")),
    )
    monkeypatch.setattr(
        o,
        "scaffold_paths",
        lambda *args: (_ for _ in ()).throw(AssertionError("scaffold created")),
    )

    with pytest.raises(RuntimeError, match="integrity failure"):
        o.open_reverse_pr("test", "provider/", "owner/repo", branch, 138, repo)

    assert writes == []


def test_open_reverse_pr_uses_snapshot_merge_instead_of_git_apply(
    tmp_path, monkeypatch
):
    repo = _init_provider_repo(tmp_path, {"provider/api.py": "old = 1\n"})
    branch = sp.run(
        ["git", "-C", repo, "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    patch = (
        "diff --git a/music_assistant/providers/test/api.py "
        "b/music_assistant/providers/test/api.py\n"
        "--- a/music_assistant/providers/test/api.py\n"
        "+++ b/music_assistant/providers/test/api.py\n"
        "@@ -1 +1 @@\n-old = 1\n+new = 1\n"
    )
    writes: list[list[str]] = []
    _mock_upstream_pr(monkeypatch, patch, writes)
    monkeypatch.setattr(o, "_fetch_upstream_commits", lambda *args: ("base", "head"))
    snapshots = (
        o.SnapshotSection(
            "provider/api.py",
            "provider/api.py",
            o.FileSnapshot(b"old = 1\n", "100644"),
            o.FileSnapshot(b"new = 1\n", "100644"),
        ),
    )
    monkeypatch.setattr(o, "_load_snapshot_sections", lambda *args: snapshots)
    monkeypatch.setattr(
        o,
        "_merge_snapshot_sections",
        lambda *args: (_ for _ in ()).throw(RuntimeError("snapshot sentinel")),
    )
    with pytest.raises(RuntimeError, match="snapshot sentinel"):
        o.open_reverse_pr("test", "provider/", "owner/repo", branch, 138, repo)

    assert writes == []
