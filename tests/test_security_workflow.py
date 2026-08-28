from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent


def test_player_audit_uses_server_python_and_ignores_metadata_mismatch() -> None:
    """Player audits retain the server runtime while auditing all pinned packages."""
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-security.yml").read_text()
    )
    steps = workflow["jobs"]["audit-player-provider"]["steps"]
    setup_uv = next(step for step in steps if step["uses"] == "astral-sh/setup-uv@v5")

    audit = next(
        step
        for step in steps
        if step.get("name") == "Run pip-audit against requirements_all.txt"
    )

    assert setup_uv["with"]["python-version"] == "3.14"
    assert audit["env"]["PIP_IGNORE_REQUIRES_PYTHON"] == "1"
