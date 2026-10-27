"""ffmpeg for provider tests: opt-out per provider, static build instead of apt."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
JOBS = ("test-music-provider", "test-player-provider")


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/reusable-test.yml").read_text())


def _steps(job: str) -> dict[str, dict]:
    return {step["name"]: step for step in _workflow()["jobs"][job]["steps"] if "name" in step}


def test_needs_ffmpeg_input_defaults_to_auto() -> None:
    """Without the input, the detect step keeps deciding by provider type."""
    workflow = _workflow()
    # PyYAML reads the "on" key as True.
    inputs = workflow[True]["workflow_call"]["inputs"]
    assert inputs["needs_ffmpeg"]["default"] == "auto"


@pytest.mark.parametrize("job", JOBS)
def test_detect_step_applies_the_needs_ffmpeg_override(job: str) -> None:
    """An explicit true/false from providers.yml overrides the provider-type default."""
    script = _steps(job)["Detect test deps"]["run"]
    assert "${{ inputs.needs_ffmpeg }}" in script
    assert 'ffmpeg_override in ("true", "false")' in script


@pytest.mark.parametrize("job", JOBS)
def test_ffmpeg_comes_from_a_cached_static_build(job: str) -> None:
    """The install restores a cached static build and verifies a fresh download."""
    steps = _steps(job)
    cache = steps["Restore ffmpeg"]
    assert cache["uses"].startswith("actions/cache@")
    install = steps["Install ffmpeg"]["run"]
    assert "sha256sum -c" in install
    # apt is only the fallback after the static download failed.
    assert install.index("BtbN/FFmpeg-Builds") < install.index("apt-get")
    for name in ("Restore ffmpeg", "Install ffmpeg"):
        assert steps[name]["if"] == "${{ steps.deps.outputs.needs_ffmpeg == 'true' }}"


def test_test_wrapper_passes_test_needs_ffmpeg_only_when_set() -> None:
    """Providers that leave test_needs_ffmpeg out keep the reusable default."""
    template = (ROOT / "wrappers/test.yml.j2").read_text()
    assert "{%- if test_needs_ffmpeg is not none %}" in template
    assert "needs_ffmpeg:" in template
