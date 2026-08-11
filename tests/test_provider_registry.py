import copy
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "a91504084610a817212c17174662cf73a4829bd9"


def _fastmcp() -> dict:
    registry = yaml.safe_load((ROOT / "providers.yml").read_text())
    return copy.deepcopy(
        next(p for p in registry["providers"] if p["domain"] == "fastmcp_server")
    )


def _errors(provider: dict) -> list:
    schema = json.loads((ROOT / "schemas/providers.schema.json").read_text())
    return list(Draft202012Validator(schema).iter_errors({"providers": [provider]}))


def test_full_lowercase_upstream_guard_baseline_is_valid() -> None:
    provider = _fastmcp()
    provider["upstream_guard_baseline"] = BASELINE
    assert _errors(provider) == []


def test_nonimmutable_upstream_guard_baselines_are_rejected() -> None:
    for invalid in ("main", "a915040", BASELINE.upper()):
        provider = _fastmcp()
        provider["upstream_guard_baseline"] = invalid
        assert _errors(provider), invalid
