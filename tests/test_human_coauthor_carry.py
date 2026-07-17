"""
Pin the human co-author carry pipeline in ``wrappers/upstream-pr.yml.j2``.

The sync commit at the upstream boundary is a single bot commit, so
contributor credit only survives if the workflow collects Co-authored-by
trailers from the synced commit range and appends them to the commit
message (AI-agent / bot trailers must NOT cross the boundary, per
AI_POLICY). These tests pin the filter pipeline text in the wrapper and
verify its behaviour by executing the same shell pipeline over samples.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WRAPPER = REPO / "wrappers/upstream-pr.yml.j2"

# The canonical pipeline pieces as they appear in the wrapper. If one of
# these drifts, update BOTH the wrapper and this test deliberately.
NORMALIZE_SED = r"s/^[Cc]o-[Aa]uthored-[Bb]y:[[:space:]]*/Co-authored-by: /"
AGENT_FILTER = (
    r"@anthropic\.com|@cursor\.com|@openai\.com|\[bot\]|github-actions"
    r"|copilot|claude|opencode|aider|devin"
)
DEDUPE_AWK = "!seen[$0]++"

SAMPLE = "\n".join(
    [
        "Co-Authored-By: Ryan Ludwig <20423360+steamEngineer@users.noreply.github.com>",
        "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>",
        "Co-authored-by: Cursor <cursoragent@cursor.com>",
        "Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>",
        "co-authored-by: github-actions[bot] <github-actions[bot]@users.noreply.github.com>",
        "Co-authored-by: OpenCode Agent <agent@opencode.dev>",
        "Co-Authored-By: Ryan Ludwig <20423360+steamEngineer@users.noreply.github.com>",
        "Co-authored-by: Marcel van der Veldt <m.vanderveldt@outlook.com>",
    ]
)


def _run_pipeline(text: str) -> list[str]:
    """Execute the wrapper's normalize → filter → dedupe pipeline verbatim."""
    script = (
        f"tr -d '\\r' | sed -E '{NORMALIZE_SED}' "
        f"| grep -Eiv '{AGENT_FILTER}' "
        f"| awk '{DEDUPE_AWK}' || true"
    )
    out = subprocess.run(
        ["bash", "-c", script], input=text, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def test_wrapper_contains_canonical_pipeline() -> None:
    """The wrapper must carry exactly the pinned normalize/filter/dedupe pieces."""
    text = WRAPPER.read_text(encoding="utf-8")
    assert NORMALIZE_SED in text, "trailer-normalization sed drifted from the pinned form"
    assert AGENT_FILTER in text, "AI/bot agent filter drifted from the pinned form"
    assert DEDUPE_AWK in text, "order-preserving dedupe drifted from the pinned form"
    assert 'git commit -m "$COMMIT_MSG" -m "$HUMAN_COAUTHORS"' in text, (
        "human co-author trailers are no longer appended to the sync commit"
    )


def test_human_trailers_survive_agents_do_not() -> None:
    """Humans pass through (normalized + deduped); AI agents and bots are dropped."""
    result = _run_pipeline(SAMPLE)
    assert result == [
        "Co-authored-by: Ryan Ludwig <20423360+steamEngineer@users.noreply.github.com>",
        "Co-authored-by: Marcel van der Veldt <m.vanderveldt@outlook.com>",
    ]


def test_all_agent_sample_yields_empty() -> None:
    """A range with only agent trailers produces no trailers (and no pipeline error)."""
    agents_only = "\n".join(
        [
            "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>",
            "Co-authored-by: Cursor <cursoragent@cursor.com>",
        ]
    )
    assert _run_pipeline(agents_only) == []
