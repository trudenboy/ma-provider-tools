"""Rendered wrappers must grant every permission their reusable workflows request.

Provider repos default the workflow token to read-only. A caller job that
omits ``permissions`` while the called reusable job asks for a write scope is
rejected at startup — for every trigger, even when the job's ``if`` would skip
it (observed as ``startup_failure`` on every Copilot Triage run).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from distribute import render_wrappers  # noqa: E402

_USES = re.compile(r"^(?:trudenboy/ma-provider-tools/|\./)\.github/workflows/([\w.-]+\.ya?ml)")
_PROVIDERS = yaml.safe_load((REPO / "providers.yml").read_text(encoding="utf-8"))["providers"]


def _requested(reusable: Path) -> dict[str, str]:
    workflow = yaml.safe_load(reusable.read_text(encoding="utf-8"))
    requested: dict[str, str] = {}
    for source in [workflow, *workflow["jobs"].values()]:
        for scope, level in (source.get("permissions") or {}).items():
            if level == "write" or scope not in requested:
                requested[scope] = level
    return requested


def _granted(caller: object, scope: str) -> str:
    if caller is None:
        return "read"  # repository default: read-only token
    if isinstance(caller, str):
        return caller.removesuffix("-all")
    return caller.get(scope, "none")


@pytest.mark.parametrize("provider", _PROVIDERS, ids=lambda p: p["domain"])
def test_callers_grant_reusable_permissions(provider: dict) -> None:
    """Each reusable-workflow call grants at least the scopes the callee requests."""
    missing = []
    for dest, content in render_wrappers(provider, _PROVIDERS).items():
        if not dest.startswith(".github/workflows/"):
            continue
        workflow = yaml.safe_load(content)
        for name, job in (workflow.get("jobs") or {}).items():
            match = _USES.match(job.get("uses", ""))
            if not match or not (REPO / ".github/workflows" / match.group(1)).exists():
                continue
            caller = job.get("permissions", workflow.get("permissions"))
            for scope, level in _requested(REPO / ".github/workflows" / match.group(1)).items():
                granted = _granted(caller, scope)
                if level == "write" and granted != "write":
                    missing.append(f"{dest}:{name} needs {scope}: write, has {granted}")
                elif level == "read" and granted not in ("read", "write"):
                    missing.append(f"{dest}:{name} needs {scope}: read, has {granted}")
    assert not missing, "\n".join(missing)
