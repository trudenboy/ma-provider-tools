"""Distribute workflow invariants."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_distribute_runs_never_overlap() -> None:
    """Overlapping distribute runs race on the same branches; they must queue."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/distribute.yml").read_text())
    assert workflow["concurrency"]["group"]
    assert workflow["concurrency"]["cancel-in-progress"] is False
