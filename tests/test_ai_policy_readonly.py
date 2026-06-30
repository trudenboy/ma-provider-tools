import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
REVERSE = [
    "reverse_sync_radar.py",
    "reverse_sync_open_pr.py",
    "check_upstream_ahead.py",
]
WRITE_VERBS = ("create", "comment", "edit", "review", "merge", "close")


def test_no_writes_to_upstream():
    """No reverse-sync script may issue a write gh command bound to UPSTREAM."""
    for name in REVERSE:
        text = (SCRIPTS / name).read_text()
        # Any `gh pr/issue <write-verb>` must not appear next to the UPSTREAM repo.
        for m in re.finditer(r'"(pr|issue)",\s*"(\w+)"', text):
            verb = m.group(2)
            if verb in WRITE_VERBS:
                # ensure UPSTREAM constant not used as --repo for this call:
                window = text[m.start() : m.start() + 400]
                assert "UPSTREAM" not in window, (
                    f"{name}: write verb {verb!r} near UPSTREAM"
                )
