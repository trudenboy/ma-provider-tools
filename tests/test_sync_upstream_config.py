"""render_ruff_toml must emit valid TOML that round-trips the upstream config."""

import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sync_upstream_config as suc  # noqa: E402


def test_per_file_ignores_glob_keys_round_trip():
    ruff_cfg = {
        "line-length": 100,
        "lint": {
            "select": ["ALL"],
            "ignore": ["ANN002"],
            "per-file-ignores": {
                "tests/**": ["S104", "S105"],
                "music_assistant/providers/_demo_*/**": ["ERA001"],
            },
        },
    }

    rendered = suc.render_ruff_toml(ruff_cfg)

    assert tomllib.loads(rendered) == ruff_cfg


def test_bare_keys_stay_unquoted():
    rendered = suc.render_ruff_toml({"lint": {"pylint": {"max-args": 10}}})

    assert "max-args = 10" in rendered
