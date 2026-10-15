"""The reusable test jobs must validate the same official Music Assistant APIs."""

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("job", ["test-music-provider", "lint", "test-player-provider"])
def test_test_jobs_use_official_music_assistant_dev(job: str) -> None:
    """A stale integration fork must not supply different APIs to player tests."""
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-test.yml").read_text()
    )
    server_checkouts = [
        step["with"]
        for step in workflow["jobs"][job]["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
        and step.get("with", {}).get("path") == "ma-server"
    ]

    assert len(server_checkouts) == 1
    assert server_checkouts[0]["repository"] == "music-assistant/server"
    assert server_checkouts[0]["ref"] == "dev"
