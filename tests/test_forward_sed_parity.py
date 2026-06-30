import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import _transform as t  # noqa: E402

DOMAIN = "yandex_music"

# Exactly the three sed expressions in
# .github/workflows/reusable-sync-to-fork.yml (test-import rewrites).
SED_EXPRS = [
    rf"s/from provider\./from music_assistant.providers.{DOMAIN}./g",
    rf"s/from provider import/from music_assistant.providers.{DOMAIN} import/g",
    rf's/"provider\./"music_assistant.providers.{DOMAIN}./g',
]

SAMPLE = (
    'from provider.api import Client\n'
    'from provider import Provider\n'
    'patch("provider.api.Client")\n'
    'x = "providerish"\n'  # must NOT match "provider. boundary
)


def _run_sed(text: str) -> str:
    for expr in SED_EXPRS:
        text = subprocess.run(
            ["sed", expr], input=text, capture_output=True, text=True, check=True
        ).stdout
    return text


def test_forward_content_matches_sed():
    assert t.forward_content("tests/test_x.py", SAMPLE, DOMAIN) == _run_sed(SAMPLE)
