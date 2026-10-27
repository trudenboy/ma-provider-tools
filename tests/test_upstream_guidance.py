"""Upstream agent-guidance mirror, its Jinja helpers, and its distribution.

`upstream-guidance/` mirrors upstream's agent docs byte for byte, pinned by
lock.json. distribute.py ships them to every provider as AGENTS.md (with
CLAUDE.md a symlink to it), Copilot instructions and two Claude skills, and
migrates hand-written guides without losing content.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import _wrapper_env as we  # noqa: E402
import distribute  # noqa: E402
import sync_upstream_guidance as sug  # noqa: E402

REGISTRY = yaml.safe_load((ROOT / "providers.yml").read_text())["providers"]


def _provider(domain: str) -> dict:
    return next(p for p in REGISTRY if p["domain"] == domain)


# --- mirror -----------------------------------------------------------------


def test_committed_mirror_matches_lock():
    assert sug.verify() == []


def test_lock_covers_every_fixed_file_and_controller_readmes():
    keys = set(sug.mirrored_paths())
    for source, paths in sug.FIXED_FILES.items():
        assert {f"{source}/{p}" for p in paths} <= keys
    assert any(k.startswith("server/music_assistant/controllers/") for k in keys)
    lock = sug.load_lock()
    for source in sug.SOURCES:
        assert len(lock["sources"][source]["sha"]) == 40


def _fake_fetch(files: dict[str, str], commit: str = "a" * 40):
    tree = [
        {"path": "music_assistant/controllers/players/README.md", "type": "blob"},
        {"path": "music_assistant/controllers/players/x.py", "type": "blob"},
        {"path": "music_assistant/providers/foo/README.md", "type": "blob"},
    ]

    def fetch(url: str) -> bytes:
        if "/commits/" in url:
            return json.dumps({"sha": commit}).encode()
        if "/git/trees/" in url:
            return json.dumps({"tree": tree}).encode()
        path = url.split(f"/{commit}/", 1)[1]
        return files.get(path, f"content of {path}\n").encode()

    return fetch


def test_snapshot_discovers_controller_readmes_only():
    _, files = sug.fetch_snapshot(_fake_fetch({}))
    assert "server/music_assistant/controllers/players/README.md" in files
    assert "server/music_assistant/controllers/players/x.py" not in files
    assert "server/music_assistant/providers/foo/README.md" not in files
    assert "org/USAGE_POLICY.md" in files


def test_write_snapshot_lock_churn_and_removal(tmp_path):
    sources, files = sug.fetch_snapshot(_fake_fetch({}))
    changed = sug.write_snapshot(sources, files, tmp_path)
    assert len(changed) == len(files)
    assert sug.verify(tmp_path) == []
    lock_before = (tmp_path / "lock.json").read_text()

    # New upstream commit, identical files: nothing rewritten.
    sources2, files2 = sug.fetch_snapshot(_fake_fetch({}, commit="b" * 40))
    assert sug.write_snapshot(sources2, files2, tmp_path) == []
    assert (tmp_path / "lock.json").read_text() == lock_before

    # A file changes and a controller README disappears upstream.
    files2 = dict(files2)
    files2["server/AGENTS.md"] = b"new rules\n"
    del files2["server/music_assistant/controllers/players/README.md"]
    changed = sug.write_snapshot(sources2, files2, tmp_path)
    assert changed == [
        "server/AGENTS.md",
        "server/music_assistant/controllers/players/README.md",
    ]
    assert not (
        tmp_path / "server/music_assistant/controllers/players/README.md"
    ).exists()
    lock = json.loads((tmp_path / "lock.json").read_text())
    assert (
        lock["files"]["server/AGENTS.md"] == hashlib.sha256(b"new rules\n").hexdigest()
    )
    assert lock["sources"]["server"]["sha"] == "b" * 40


def test_verify_reports_local_edits_and_strays(tmp_path):
    sources, files = sug.fetch_snapshot(_fake_fetch({}))
    sug.write_snapshot(sources, files, tmp_path)
    (tmp_path / "server/AGENTS.md").write_text("edited\n")
    (tmp_path / "org/EXTRA.md").write_text("x\n")
    assert sug.verify(tmp_path) == [
        "modified: server/AGENTS.md",
        "untracked: org/EXTRA.md",
    ]


# --- Jinja helpers ----------------------------------------------------------


def test_demote_headings_skips_code_fences():
    text = "# A\n## B\n```python\n# comment\n```\n###### deep\n"
    assert we.demote_headings(text) == (
        "## A\n### B\n```python\n# comment\n```\n###### deep\n"
    )


def test_title_and_frontmatter_helpers():
    doc = '---\napplyTo: "**"\n---\n\n# Title\nbody\n'
    assert we.frontmatter(doc) == '---\napplyTo: "**"\n---\n'
    assert we.strip_frontmatter(doc) == "# Title\nbody\n"
    assert we.strip_title("# Title\n\nbody\n") == "body\n"


def test_upstream_file_rejects_paths_outside_mirror():
    with pytest.raises(FileNotFoundError):
        we.upstream_file("../providers.yml")
    with pytest.raises(FileNotFoundError):
        we.upstream_file("server/NOPE.md")


def test_upstream_braces_are_not_reparsed(monkeypatch, tmp_path):
    (tmp_path / "server").mkdir()
    (tmp_path / "server/X.md").write_text("use ${{ secrets.X }} and {% raw %}\n")
    monkeypatch.setattr(we, "GUIDANCE_DIR", tmp_path)
    out = we.make_env().from_string("{{ upstream_file('server/X.md') }}").render()
    assert out == "use ${{ secrets.X }} and {% raw %}\n"


# --- rendering --------------------------------------------------------------


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    return distribute.render_wrappers(_provider("yandex_music"), REGISTRY)


def test_agents_md_replaces_claude_md(rendered):
    assert "AGENTS.md" in rendered
    assert "CLAUDE.md" not in rendered
    assert distribute.SYMLINKS == {"CLAUDE.md": "AGENTS.md"}


def test_agents_md_content(rendered):
    agents = rendered["AGENTS.md"]
    assert agents.startswith(distribute.AGENTS_RENDERED_MARKER)
    assert [line for line in agents.splitlines() if line.startswith("# ")] == [
        "# AGENTS.md"
    ]
    for needle in (
        "## Upstream vs Ecosystem Conventions",
        "## Upstream Engineering Rules (MUST)",
        "**Usage policy.**",
        "max_concurrent_streams",
        "ask the developer how to migrate",
        "### Upstream Rule Gate",
        "## Upstream Agent Guide (verbatim)",
        "CLAUDE.local.md",
    ):
        assert needle in agents, needle
    upstream = we.upstream_file("server/AGENTS.md")
    assert we.demote_headings(we.strip_title(upstream)).strip() in agents
    assert agents.endswith("\n") and not agents.endswith("\n\n")


def test_vendored_files_are_byte_identical(rendered):
    vendored = distribute.vendored_files()
    assert vendored, "no vendored files mapped"
    for dest, key in vendored.items():
        assert rendered[dest] == we.upstream_file(key), dest
    assert (
        ".claude/skills/ma-upstream-standards/references/controllers/players.md"
        in rendered
    )
    assert ".github/instructions/music-assistant-standards.instructions.md" in rendered


def test_copilot_and_pr_description_compose_upstream(rendered):
    copilot = rendered[".github/copilot-instructions.md"]
    assert copilot.startswith(distribute.COPILOT_RENDERED_MARKER)
    assert "Conventional Commit" in copilot
    assert "### Severity" in copilot  # upstream heading, demoted
    pr = rendered[".github/instructions/music-assistant-pr-description.instructions.md"]
    assert pr.startswith('---\napplyTo: "**"\n---\n')
    assert "Scope in provider repos" in pr
    assert (
        we.strip_frontmatter(
            we.upstream_file(
                "server/.github/instructions/music-assistant-pr-description.instructions.md"
            )
        ).strip()
        in pr
    )


def test_skills_have_frontmatter_names(rendered):
    for name in ("ma-review-pr", "ma-upstream-standards"):
        skill = rendered[f".claude/skills/{name}/SKILL.md"]
        assert skill.startswith(f"---\nname: {name}\n")


def test_player_provider_skill_points_at_player_controllers():
    out = distribute.render_wrappers(_provider("yandex_station"), REGISTRY)
    assert (
        "start with `players`" in out[".claude/skills/ma-upstream-standards/SKILL.md"]
    )


def test_server_fork_gets_no_agent_guidance():
    out = distribute.render_wrappers(_provider("ma_server"), REGISTRY)
    assert not [k for k in out if k == "AGENTS.md" or k.startswith(".claude/")]
    assert "scripts/check_upstream_rules.py" not in out
    assert ".github/copilot-instructions.md" not in out


def test_pre_commit_runs_upstream_rules_gate(rendered):
    cfg = yaml.safe_load(rendered[".pre-commit-config.yaml"])
    hooks = {h["id"]: h for repo in cfg["repos"] for h in repo["hooks"]}
    hook = hooks["check-upstream-rules"]
    assert hook["entry"].endswith("python scripts/check_upstream_rules.py")
    assert hook["pass_filenames"] is False


# --- migrations in a provider clone -----------------------------------------


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    return tmp_path


def test_rendered_claude_md_becomes_symlink(clone, rendered):
    (clone / "CLAUDE.md").write_text(distribute.CLAUDE_RENDERED_MARKER + "\nold\n")
    _git(clone, "add", "CLAUDE.md")
    assert distribute.migrate_agent_guides(str(clone), rendered) is False
    assert distribute.apply_symlinks(str(clone), rendered) is True
    link = clone / "CLAUDE.md"
    assert link.is_symlink() and link.readlink() == Path("AGENTS.md")
    assert "120000" in _git(clone, "ls-files", "-s", "CLAUDE.md")
    assert not (clone / "CLAUDE.local.md").exists()
    assert distribute.apply_symlinks(str(clone), rendered) is False


def test_hand_written_agents_md_moves_into_claude_local(clone, rendered):
    (clone / "CLAUDE.local.md").write_text("# Local\n\nnotes\n")
    (clone / "AGENTS.md").write_text("# AGENTS.md\n\n## Structure\nmap\n")
    assert distribute.migrate_agent_guides(str(clone), rendered) is True
    local = (clone / "CLAUDE.local.md").read_text()
    assert local.startswith(
        "# Local\n\nnotes\n\n## Project map (migrated from AGENTS.md)"
    )
    assert "### Structure\nmap" in local
    # Second run (AGENTS.md now rendered) leaves it alone.
    (clone / "AGENTS.md").write_text(rendered["AGENTS.md"])
    assert distribute.migrate_agent_guides(str(clone), rendered) is False


def test_hand_written_claude_md_moves_to_claude_local(clone, rendered):
    (clone / "CLAUDE.md").write_text("# Mine\n")
    assert distribute.migrate_agent_guides(str(clone), rendered) is True
    assert (clone / "CLAUDE.local.md").read_text() == "# Mine\n"


def test_hand_written_copilot_instructions_keep_applying(clone, rendered):
    (clone / ".github").mkdir()
    (clone / ".github/copilot-instructions.md").write_text("# Provider notes\n")
    assert distribute.migrate_agent_guides(str(clone), rendered) is True
    moved = (clone / distribute.PROVIDER_COPILOT_INSTRUCTIONS).read_text()
    assert moved == '---\napplyTo: "**"\n---\n\n# Provider notes\n'
    assert distribute.PROVIDER_COPILOT_INSTRUCTIONS in _git(
        clone, "diff", "--cached", "--name-only"
    )


def test_hand_written_claude_md_appends_when_local_exists(clone, rendered):
    (clone / "CLAUDE.local.md").write_text("# Local\n")
    (clone / "CLAUDE.md").write_text("# Mine\n\n## Flow\nsteps\n")
    assert distribute.migrate_agent_guides(str(clone), rendered) is True
    local = (clone / "CLAUDE.local.md").read_text()
    assert "## Project map (migrated from CLAUDE.md)" in local
    assert "### Flow\nsteps" in local


def test_hand_written_copilot_appends_to_existing_provider_instructions(
    clone, rendered
):
    target = clone / distribute.PROVIDER_COPILOT_INSTRUCTIONS
    target.parent.mkdir(parents=True)
    target.write_text('---\napplyTo: "**"\n---\n\nold\n')
    (clone / ".github/copilot-instructions.md").write_text("new notes\n")
    assert distribute.migrate_agent_guides(str(clone), rendered) is True
    assert target.read_text().endswith("old\n\nnew notes\n")


def test_stale_controller_docs_are_pruned(clone, rendered):
    refs = clone / distribute.UPSTREAM_STANDARDS_REFS / "controllers"
    refs.mkdir(parents=True)
    (refs / "players.md").write_text("x\n")
    (refs / "gone.md").write_text("x\n")
    _git(clone, "add", "-f", ".")
    assert distribute.prune_vendored(str(clone), rendered) is True
    assert not (refs / "gone.md").exists()
    assert (refs / "players.md").exists()


def test_pre_commit_skips_upstream_guidance_only(rendered):
    import re

    pattern = re.compile(yaml.safe_load(rendered[".pre-commit-config.yaml"])["exclude"])
    for path in (
        "AGENTS.md",
        ".github/copilot-instructions.md",
        ".github/instructions/music-assistant-standards.instructions.md",
        ".claude/skills/ma-upstream-standards/references/controllers/webserver.md",
        ".claude/skills/ma-review-pr/SKILL.md",
    ):
        assert pattern.match(path), path
    for path in (
        ".github/instructions/provider.instructions.md",
        "CLAUDE.local.md",
        "provider/__init__.py",
        "README.md",
    ):
        assert not pattern.match(path), path


@pytest.mark.parametrize(
    "plant",
    [
        lambda c, out: (c / "CLAUDE.local.md").symlink_to(out / "victim"),
        lambda c, out: (c / ".github").symlink_to(out, target_is_directory=True),
    ],
)
def test_migration_refuses_symlinks_out_of_the_clone(clone, rendered, tmp_path, plant):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "victim").write_text("untouched\n")
    plant(clone, outside)
    (clone / "AGENTS.md").write_text("# hand-written\n")
    with pytest.raises(RuntimeError, match="symlink"):
        distribute.migrate_agent_guides(str(clone), rendered)
    assert (outside / "victim").read_text() == "untouched\n"
    assert sorted(p.name for p in outside.iterdir()) == ["victim"]


def test_safe_path_rejects_escapes_and_symlinked_parents(clone, tmp_path):
    (clone / ".claude").symlink_to(tmp_path, target_is_directory=True)
    for rel in ("../x", "/etc/passwd", ".git/config", ".claude/skills/a/SKILL.md"):
        with pytest.raises(RuntimeError):
            distribute.safe_path(str(clone), rel)
    (clone / "CLAUDE.md").symlink_to("AGENTS.md")
    assert distribute.safe_path(str(clone), "CLAUDE.md", allow_final_symlink=True)
