import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import _transform as t  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOMAIN = "yandex_music"
PKG = f"music_assistant.providers.{DOMAIN}"

# The canonical forward rule set (issue #99). GNU-sed BRE form, unescaped, with
# the package substituted. `scripts/_transform.py` mirrors these; the two
# forward `sed` blocks in the workflows are pinned to them below.
CANON_SED = [
    rf"s/\bfrom provider\./from {PKG}./g",
    rf"s/\bfrom provider import\b/from {PKG} import/g",
    rf"s/\bimport provider\./import {PKG}./g",
    rf"s/\bimport provider\(\s\+as\s\)/import {PKG}\1/g",
    rf"s/\bimport provider$/import {PKG}/g",
    rf's/"provider\./"{PKG}./g',
    rf"s/'provider\./'{PKG}./g",
]

# The same expressions as they appear in the workflow YAML (shell-escaped, with
# the ${NEW_PKG} variable). Both forward `sed` blocks must contain all of them.
ESCAPED_EXPRS = [
    r"s/\\bfrom provider\\./from ${NEW_PKG}./g",
    r"s/\\bfrom provider import\\b/from ${NEW_PKG} import/g",
    r"s/\\bimport provider\\./import ${NEW_PKG}./g",
    r"s/\\bimport provider\\(\\s\\+as\\s\\)/import ${NEW_PKG}\\1/g",
    r"s/\\bimport provider\$/import ${NEW_PKG}/g",
    r"s/\"provider\\./\"${NEW_PKG}./g",
    r"s/'provider\\./'${NEW_PKG}./g",
]

WORKFLOWS = [
    REPO / ".github/workflows/reusable-sync-to-fork.yml",
    REPO / "wrappers/upstream-pr.yml.j2",
]

SAMPLE = (
    "from provider.api import Client\n"
    "from provider import Provider\n"
    "import provider.debug.buf as buf\n"
    "import provider as prov\n"
    "import provider\n"
    'patch("provider.api.Client")\n'
    "patch('provider.api.Other')\n"
    'x = "providerish"\n'  # must NOT match the "provider. boundary
    "    provider.login()\n"  # bare fixture attr access — must NOT match
)


def _run_sed(text: str) -> str:
    for expr in CANON_SED:
        text = subprocess.run(
            ["sed", expr], input=text, capture_output=True, text=True, check=True
        ).stdout
    return text


def test_forward_content_matches_canonical_sed():
    """_transform.forward_content reproduces the canonical sed rule set."""
    assert t.forward_content("tests/test_x.py", SAMPLE, DOMAIN) == _run_sed(SAMPLE)


def test_both_workflow_sed_blocks_contain_canonical_rules():
    """Both forward sed blocks are pinned to the canonical rule set, so neither
    workflow can drift from scripts/_transform.py (issue #99)."""
    for wf in WORKFLOWS:
        text = wf.read_text()
        for expr in ESCAPED_EXPRS:
            assert expr in text, f"{wf.name} missing canonical sed expr: {expr}"
