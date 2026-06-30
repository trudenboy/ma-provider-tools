import sys
from pathlib import Path

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
