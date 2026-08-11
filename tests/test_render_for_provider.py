"""render_for_provider must handle nested template paths and skip_wrappers
(issue #115: scripts/check_method_order.py.j2 renders into _expected/scripts/
and must not be rendered for providers that skip the wrapper).
"""

import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "render_for_provider.py"
BASELINE = "a91504084610a817212c17174662cf73a4829bd9"


def _run(domain: str, out_dir: Path, *templates: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--domain",
            domain,
            "--out-dir",
            str(out_dir),
            *templates,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_nested_template_renders_into_subdir(tmp_path: Path) -> None:
    res = _run("yandex_music", tmp_path, "scripts/check_method_order.py.j2")
    assert res.returncode == 0, res.stderr
    out = tmp_path / "scripts" / "check_method_order.py"
    assert out.is_file()
    assert "provider" in out.read_text()


def test_skip_wrappers_template_not_rendered(tmp_path: Path) -> None:
    res = _run("ma_server", tmp_path, "scripts/check_method_order.py.j2")
    assert res.returncode == 0, res.stderr
    assert not (tmp_path / "scripts" / "check_method_order.py").exists()


def test_fastmcp_runtime_dependencies_match_its_manifest(tmp_path: Path) -> None:
    """A clean FastMCP environment installs every provider runtime dependency."""
    result = _run("fastmcp_server", tmp_path, "pyproject.toml.j2")
    assert result.returncode == 0, result.stderr
    project = tomllib.loads((tmp_path / "pyproject.toml").read_text())

    assert project["project"]["dependencies"] == [
        "fastmcp==3.4.6",
        "prefab-ui==0.20.2",
    ]


def _rendered_compose(domain: str, tmp_path: Path) -> dict:
    result = _run(domain, tmp_path, "docker-compose.dev.yml.j2")
    assert result.returncode == 0, result.stderr
    return yaml.safe_load((tmp_path / "docker-compose.dev.yml").read_text())


def test_fastmcp_compose_mounts_neighboring_ma_source(tmp_path: Path) -> None:
    """FastMCP integration tests execute the checked-out MA source and provider."""
    service = _rendered_compose("fastmcp_server", tmp_path)["services"]["ma"]

    assert service["environment"] == {"PYTHONPATH": "/ma-server"}
    assert "${MA_SERVER_ROOT:-../ma-server}:/ma-server:ro" in service["volumes"]
    assert (
        "./provider/:/ma-server/music_assistant/providers/fastmcp_server:ro"
        in service["volumes"]
    )
    assert "./tests/:/tmp/provider-tests:ro" in service["volumes"]
    assert "./provider/:/tmp/provider:ro" not in service["volumes"]


def test_ordinary_provider_compose_keeps_generic_overlay(tmp_path: Path) -> None:
    """The FastMCP source checkout does not become a global wrapper requirement."""
    service = _rendered_compose("yandex_music", tmp_path)["services"]["ma"]

    assert "environment" not in service
    assert "./provider/:/tmp/provider:ro" in service["volumes"]
    assert all("/ma-server" not in mount for mount in service["volumes"])


def test_fastmcp_init_validates_source_imports(tmp_path: Path) -> None:
    """FastMCP startup rejects fallback to the image's installed provider."""
    result = _run("fastmcp_server", tmp_path, "scripts/docker-init.sh.j2")
    assert result.returncode == 0, result.stderr
    script = (tmp_path / "scripts" / "docker-init.sh").read_text()

    assert "export PYTHONPATH=\"/ma-server${PYTHONPATH:+:$PYTHONPATH}\"" in script
    assert "/ma-server/music_assistant/providers/fastmcp_server/*" in script
    assert "ln -s /tmp/provider" not in script


def test_ordinary_provider_init_keeps_symlink_mode(tmp_path: Path) -> None:
    """Providers without source-overlay metadata still link into site-packages."""
    result = _run("yandex_music", tmp_path, "scripts/docker-init.sh.j2")
    assert result.returncode == 0, result.stderr
    script = (tmp_path / "scripts" / "docker-init.sh").read_text()

    assert "ln -s /tmp/provider" in script
    assert "export PYTHONPATH=\"/ma-server" not in script


def _rendered_pipeline(domain: str, tmp_path: Path) -> dict:
    result = _run(domain, tmp_path, "pipeline.yml.j2")
    assert result.returncode == 0, result.stderr
    return yaml.safe_load((tmp_path / "pipeline.yml").read_text())


def test_fastmcp_pipeline_passes_upstream_guard_baseline(tmp_path: Path) -> None:
    jobs = _rendered_pipeline("fastmcp_server", tmp_path)["jobs"]
    assert jobs["sync-integration"]["with"]["upstream_guard_baseline"] == BASELINE
    assert jobs["sync-upstream"]["with"]["upstream_guard_baseline"] == BASELINE


def test_ordinary_pipeline_has_no_upstream_guard_baseline(tmp_path: Path) -> None:
    jobs = _rendered_pipeline("yandex_music", tmp_path)["jobs"]
    assert "upstream_guard_baseline" not in jobs["sync-integration"]["with"]
    assert "upstream_guard_baseline" not in jobs["sync-upstream"]["with"]


def test_distributor_renders_fastmcp_pipeline_with_baseline() -> None:
    from scripts.distribute import render_wrappers

    registry = yaml.safe_load((REPO_ROOT / "providers.yml").read_text())
    provider = next(
        p for p in registry["providers"] if p["domain"] == "fastmcp_server"
    )
    rendered = render_wrappers(provider, registry["providers"])
    jobs = yaml.safe_load(rendered[".github/workflows/pipeline.yml"])["jobs"]
    assert jobs["sync-integration"]["with"]["upstream_guard_baseline"] == BASELINE


def _rendered_manual_sync(domain: str, tmp_path: Path) -> dict:
    result = _run(domain, tmp_path, "sync-to-fork.yml.j2")
    assert result.returncode == 0, result.stderr
    return yaml.safe_load((tmp_path / "sync-to-fork.yml").read_text())


def test_fastmcp_manual_sync_passes_upstream_guard_baseline(tmp_path: Path) -> None:
    job = _rendered_manual_sync("fastmcp_server", tmp_path)["jobs"]["sync"]
    assert job["with"]["upstream_guard_baseline"] == BASELINE


def test_ordinary_manual_sync_has_no_upstream_guard_baseline(tmp_path: Path) -> None:
    job = _rendered_manual_sync("yandex_music", tmp_path)["jobs"]["sync"]
    assert "upstream_guard_baseline" not in job["with"]


def _rendered_backport(domain: str, tmp_path: Path) -> dict:
    result = _run(domain, tmp_path, "backport.yml.j2")
    assert result.returncode == 0, result.stderr
    return yaml.safe_load((tmp_path / "backport.yml").read_text())


def test_fastmcp_backport_passes_upstream_guard_baseline(tmp_path: Path) -> None:
    job = _rendered_backport("fastmcp_server", tmp_path)["jobs"]["backport"]
    assert job["with"]["upstream_guard_baseline"] == BASELINE


def test_ordinary_backport_has_no_upstream_guard_baseline(tmp_path: Path) -> None:
    job = _rendered_backport("yandex_music", tmp_path)["jobs"]["backport"]
    assert "upstream_guard_baseline" not in job["with"]
