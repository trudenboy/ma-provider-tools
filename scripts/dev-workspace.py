#!/usr/bin/env python3
"""Create and manage a shared development workspace for Music Assistant custom providers.

Clones ma-server and selected provider repos, wires them together with symlinks
so that ``python -m music_assistant`` sees every custom provider, and keeps the
whole workspace up-to-date with a single command.

Usage:
    python3 scripts/dev-workspace.py init [--dir PATH] [--providers d1,d2] [--all]
    python3 scripts/dev-workspace.py update [--dir PATH]
    python3 scripts/dev-workspace.py add DOMAIN [--dir PATH]
    python3 scripts/dev-workspace.py status [--dir PATH]
    python3 scripts/dev-workspace.py run [--dir PATH] [--log-level LEVEL]
"""

# Auto-generated scripts should not be edited manually, but this file
# lives in ma-provider-tools itself and IS manually maintained.

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PROVIDERS_FILE = REPO_ROOT / "providers.yml"
DEFAULT_WORKSPACE = Path.home() / "ma-workspace"
MA_SERVER_REPO = "https://github.com/trudenboy/ma-server.git"
MA_SERVER_BRANCH = "dev"
WORKSPACE_STATE_FILE = "workspace.yml"

# ANSI helpers
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_BOLD = "\033[1m"
_RESET = "\033[0m"

VERBOSE = False


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _ok(msg: str) -> None:
    print(f"  {_GREEN}✓{_RESET} {msg}")


def _err(msg: str) -> None:
    print(f"  {_RED}✗{_RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}⚠{_RESET} {msg}")


def _header(msg: str) -> None:
    print(f"\n{_BOLD}{msg}{_RESET}")


def _debug(msg: str) -> None:
    if VERBOSE:
        print(f"  [debug] {msg}")


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, optionally merging *env* into the current environment."""
    run_env = {**os.environ, **(env or {})}
    _debug(f"$ {' '.join(cmd)}")
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            env=run_env,
            check=check,
            text=True,
            capture_output=capture,
        )
    except subprocess.CalledProcessError as exc:
        if capture and exc.stderr:
            _err(exc.stderr.strip())
        raise


def _git_head_sha(repo_dir: Path) -> str:
    result = _run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        capture=True,
    )
    return result.stdout.strip()


def _git_branch(repo_dir: Path) -> str:
    result = _run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_dir,
        capture=True,
    )
    return result.stdout.strip()


def _repo_name(repo_slug: str) -> str:
    """Extract the repo name from an owner/repo slug."""
    return repo_slug.split("/", 1)[-1]


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def load_registry() -> list[dict]:
    """Return the providers list from providers.yml."""
    data = yaml.safe_load(PROVIDERS_FILE.read_text())
    return data.get("providers", [])


def find_provider(registry: list[dict], domain: str) -> dict | None:
    for p in registry:
        if p["domain"] == domain:
            return p
    return None


def installable_providers(
    registry: list[dict],
    domains: list[str] | None = None,
    use_all: bool = False,
) -> list[dict]:
    """Filter the registry to providers that should be installed."""
    candidates = [p for p in registry if p.get("provider_type") != "server_fork"]
    if use_all:
        return candidates
    if domains:
        selected = []
        for d in domains:
            match = find_provider(candidates, d)
            if match:
                selected.append(match)
            else:
                _warn(f"Domain '{d}' not found in providers.yml (or is server_fork)")
        return selected
    return candidates


# ---------------------------------------------------------------------------
# Workspace state
# ---------------------------------------------------------------------------


def _state_path(ws: Path) -> Path:
    return ws / WORKSPACE_STATE_FILE


def load_state(ws: Path) -> dict:
    p = _state_path(ws)
    if p.exists():
        return yaml.safe_load(p.read_text()) or {}
    return {}


def save_state(ws: Path, state: dict) -> None:
    _state_path(ws).write_text(
        yaml.dump(state, default_flow_style=False, sort_keys=False)
    )


def build_state(ws: Path, providers: list[dict]) -> dict:
    server_dir = ws / "ma-server"
    state: dict = {
        "workspace": str(ws),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ma_server": {
            "branch": _git_branch(server_dir),
            "commit": _git_head_sha(server_dir),
        },
        "providers": [],
    }
    for p in providers:
        name = _repo_name(p["repo"])
        repo_dir = ws / "providers" / name
        entry: dict = {
            "domain": p["domain"],
            "repo": p["repo"],
        }
        if repo_dir.exists():
            entry["branch"] = _git_branch(repo_dir)
            entry["commit"] = _git_head_sha(repo_dir)
        state["providers"].append(entry)
    return state


# ---------------------------------------------------------------------------
# Provider installation helper
# ---------------------------------------------------------------------------


def _venv_env(ws: Path) -> dict[str, str]:
    return {"VIRTUAL_ENV": str(ws / ".venv")}


def install_provider(ws: Path, provider: dict) -> None:
    """Clone a single provider, create its symlink, install deps, set up pre-commit."""
    domain = provider["domain"]
    repo_slug = provider["repo"]
    name = _repo_name(repo_slug)
    branch = provider.get("default_branch", "dev")
    provider_path = provider.get("provider_path", "provider/")

    providers_dir = ws / "providers"
    repo_dir = providers_dir / name
    server_providers = ws / "ma-server" / "music_assistant" / "providers"

    # 1. Clone
    if repo_dir.exists():
        _warn(f"{name} already cloned — skipping clone")
    else:
        _header(f"Cloning {repo_slug} ({branch})")
        _run(
            [
                "git",
                "clone",
                "-b",
                branch,
                f"https://github.com/{repo_slug}.git",
                str(repo_dir),
            ]
        )
        _ok(f"Cloned {name}")

    # 2. Symlink
    link = server_providers / domain
    # Target: relative path from the symlink's parent to the provider directory
    target = Path(os.path.relpath(repo_dir / provider_path, link.parent))
    if link.exists() or link.is_symlink():
        if link.is_symlink() and Path(os.readlink(str(link))) == target:
            _ok(f"Symlink {domain} → already correct")
        else:
            _warn(f"Symlink {domain} exists but differs — replacing")
            link.unlink()
            link.symlink_to(target)
            _ok(f"Symlink {domain} → {target}")
    else:
        link.symlink_to(target)
        _ok(f"Symlink {domain} → {target}")

    # 3. Install runtime requirements from manifest.json
    manifest_path = repo_dir / provider.get("manifest_path", "provider/manifest.json")
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            reqs = manifest.get("requirements", [])
            if reqs:
                _debug(f"Installing requirements: {reqs}")
                _run(
                    ["uv", "pip", "install", *reqs],
                    env=_venv_env(ws),
                )
                _ok(f"Installed {len(reqs)} requirement(s) from manifest.json")
            else:
                _debug("No requirements in manifest.json")
        except (json.JSONDecodeError, OSError) as exc:
            _warn(f"Could not parse manifest.json: {exc}")
    else:
        _warn(f"manifest.json not found at {manifest_path}")

    # 4. pre-commit install
    if (repo_dir / ".pre-commit-config.yaml").exists():
        try:
            _run(["pre-commit", "install"], cwd=repo_dir, capture=True)
            _ok("pre-commit hooks installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            _warn("pre-commit install failed (is pre-commit installed?)")
    else:
        _debug("No .pre-commit-config.yaml — skipping pre-commit install")


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> None:
    ws = Path(args.dir).expanduser().resolve()
    _header(f"Initialising workspace at {ws}")

    registry = load_registry()
    providers = installable_providers(
        registry,
        domains=args.providers.split(",") if args.providers else None,
        use_all=args.all,
    )

    if not providers:
        _err("No providers selected. Use --all or --providers domain1,domain2")
        sys.exit(1)

    print(f"  Providers: {', '.join(p['domain'] for p in providers)}")

    # Create directories
    (ws / "providers").mkdir(parents=True, exist_ok=True)

    # 1. Clone ma-server
    server_dir = ws / "ma-server"
    if server_dir.exists():
        _warn("ma-server already cloned — skipping")
    else:
        _header("Cloning ma-server")
        _run(
            [
                "git",
                "clone",
                "-b",
                MA_SERVER_BRANCH,
                MA_SERVER_REPO,
                str(server_dir),
            ]
        )
        _ok("Cloned ma-server")

    # 2. Create venv
    venv_dir = ws / ".venv"
    if venv_dir.exists():
        _warn(".venv already exists — skipping creation")
    else:
        _header("Creating virtual environment")
        _run(["uv", "venv", "--python", "3.12", str(venv_dir)])
        _ok("Created .venv (Python 3.12)")

    # 3. Install MA server in editable mode
    _header("Installing Music Assistant server")
    _run(
        [
            "uv",
            "pip",
            "install",
            "-e",
            str(server_dir),
            "-e",
            f"{server_dir}[test]",
        ],
        env=_venv_env(ws),
    )
    _ok("Installed MA server (editable)")

    # 4. Install requirements_all.txt
    reqs_file = server_dir / "requirements_all.txt"
    if reqs_file.exists():
        _header("Installing server requirements")
        _run(
            ["uv", "pip", "install", "-r", str(reqs_file)],
            env=_venv_env(ws),
        )
        _ok("Installed requirements_all.txt")
    else:
        _warn("requirements_all.txt not found — skipping")

    # 5. Install each provider
    for p in providers:
        install_provider(ws, p)

    # 6. Write state
    state = build_state(ws, providers)
    save_state(ws, state)
    _ok(f"Wrote {WORKSPACE_STATE_FILE}")

    _header("Workspace ready 🚀")
    print(f"  Activate venv:  source {ws / '.venv' / 'bin' / 'activate'}")
    print(f"  Run server:     python3 scripts/dev-workspace.py run --dir {ws}")


def cmd_update(args: argparse.Namespace) -> None:
    ws = Path(args.dir).expanduser().resolve()
    state = load_state(ws)
    if not state:
        _err(f"No workspace.yml found in {ws} — run init first")
        sys.exit(1)

    _header(f"Updating workspace at {ws}")

    # Pull ma-server
    server_dir = ws / "ma-server"
    if server_dir.exists():
        _header("Updating ma-server")
        _run(["git", "-C", str(server_dir), "pull", "--rebase"])
        _ok(f"ma-server @ {_git_head_sha(server_dir)[:10]}")
    else:
        _err("ma-server directory missing — re-run init")
        sys.exit(1)

    # Pull each provider
    registry = load_registry()
    installed = state.get("providers", [])
    for entry in installed:
        domain = entry["domain"]
        repo_slug = entry["repo"]
        name = _repo_name(repo_slug)
        repo_dir = ws / "providers" / name
        if repo_dir.exists():
            _header(f"Updating {name}")
            _run(["git", "-C", str(repo_dir), "pull", "--rebase"])
            _ok(f"{domain} @ {_git_head_sha(repo_dir)[:10]}")
        else:
            _warn(f"{name} directory missing — skipping (use 'add' to re-install)")

    # Reinstall MA + deps
    _header("Reinstalling MA server + deps")
    _run(
        [
            "uv",
            "pip",
            "install",
            "-e",
            str(server_dir),
            "-e",
            f"{server_dir}[test]",
        ],
        env=_venv_env(ws),
    )
    reqs_file = server_dir / "requirements_all.txt"
    if reqs_file.exists():
        _run(
            ["uv", "pip", "install", "-r", str(reqs_file)],
            env=_venv_env(ws),
        )
    _ok("Reinstalled MA server + deps")

    # Rebuild state
    provider_dicts = []
    for entry in installed:
        p = find_provider(registry, entry["domain"])
        if p:
            provider_dicts.append(p)
        else:
            provider_dicts.append(entry)
    new_state = build_state(ws, provider_dicts)
    new_state["providers"] = state.get("providers", [])
    # Update SHAs
    new_state["ma_server"]["commit"] = _git_head_sha(server_dir)
    new_state["ma_server"]["branch"] = _git_branch(server_dir)
    for sp in new_state["providers"]:
        name = _repo_name(sp["repo"])
        repo_dir = ws / "providers" / name
        if repo_dir.exists():
            sp["commit"] = _git_head_sha(repo_dir)
            sp["branch"] = _git_branch(repo_dir)
    new_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state(ws, new_state)
    _ok(f"Updated {WORKSPACE_STATE_FILE}")


def cmd_add(args: argparse.Namespace) -> None:
    ws = Path(args.dir).expanduser().resolve()
    state = load_state(ws)
    if not state:
        _err(f"No workspace.yml found in {ws} — run init first")
        sys.exit(1)

    domain = args.domain
    registry = load_registry()
    provider = find_provider(registry, domain)
    if not provider:
        _err(f"Domain '{domain}' not found in providers.yml")
        sys.exit(1)
    if provider.get("provider_type") == "server_fork":
        _err(f"Domain '{domain}' is a server_fork — cannot add as provider")
        sys.exit(1)

    # Check if already installed
    installed_domains = [p["domain"] for p in state.get("providers", [])]
    if domain in installed_domains:
        _warn(f"{domain} is already in workspace.yml — reinstalling anyway")

    _header(f"Adding {domain} to workspace")
    install_provider(ws, provider)

    # Update state
    if domain not in installed_domains:
        state.setdefault("providers", []).append(
            {
                "domain": domain,
                "repo": provider["repo"],
                "branch": _git_branch(ws / "providers" / _repo_name(provider["repo"])),
                "commit": _git_head_sha(
                    ws / "providers" / _repo_name(provider["repo"])
                ),
            }
        )
    else:
        for sp in state["providers"]:
            if sp["domain"] == domain:
                repo_dir = ws / "providers" / _repo_name(provider["repo"])
                sp["commit"] = _git_head_sha(repo_dir)
                sp["branch"] = _git_branch(repo_dir)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state(ws, state)
    _ok(f"Updated {WORKSPACE_STATE_FILE}")


def cmd_status(args: argparse.Namespace) -> None:
    ws = Path(args.dir).expanduser().resolve()
    state = load_state(ws)
    if not state:
        _err(f"No workspace.yml found in {ws} — run init first")
        sys.exit(1)

    venv_dir = ws / ".venv"
    server_dir = ws / "ma-server"
    server_providers = server_dir / "music_assistant" / "providers"

    _header("Workspace")
    print(f"  Path:   {ws}")
    print(f"  venv:   {venv_dir}  {'(exists)' if venv_dir.exists() else '(MISSING)'}")

    _header("ma-server")
    if server_dir.exists():
        branch = _git_branch(server_dir)
        sha = _git_head_sha(server_dir)
        print(f"  Branch: {branch}")
        print(f"  Commit: {sha[:10]}")
    else:
        _err("Directory missing!")

    _header("Providers")
    for entry in state.get("providers", []):
        domain = entry["domain"]
        repo_slug = entry["repo"]
        name = _repo_name(repo_slug)
        repo_dir = ws / "providers" / name

        if repo_dir.exists():
            branch = _git_branch(repo_dir)
            sha = _git_head_sha(repo_dir)
        else:
            branch = "?"
            sha = "?"

        link = server_providers / domain
        if link.is_symlink():
            if link.resolve().exists():
                link_status = f"{_GREEN}OK{_RESET}"
            else:
                link_status = f"{_RED}BROKEN{_RESET}"
        else:
            link_status = f"{_YELLOW}MISSING{_RESET}"

        print(
            f"  {_BOLD}{domain}{_RESET}  "
            f"repo={repo_slug}  branch={branch}  "
            f"commit={sha[:10] if sha != '?' else sha}  "
            f"symlink={link_status}"
        )


def cmd_run(args: argparse.Namespace) -> None:
    ws = Path(args.dir).expanduser().resolve()
    venv_python = ws / ".venv" / "bin" / "python"
    data_dir = ws / ".ma-data"

    if not venv_python.exists():
        _err(f"venv python not found at {venv_python} — run init first")
        sys.exit(1)

    data_dir.mkdir(parents=True, exist_ok=True)

    log_level = args.log_level
    cmd = [
        str(venv_python),
        "-m",
        "music_assistant",
        "--data-dir",
        str(data_dir),
        "--log-level",
        log_level,
    ]
    _header(f"Starting Music Assistant (log-level={log_level})")
    print(f"  Data dir: {data_dir}")
    print(f"  Command:  {' '.join(cmd)}\n")

    try:
        os.execv(str(venv_python), cmd)
    except OSError as exc:
        _err(f"Failed to start: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    global VERBOSE  # noqa: PLW0603

    parser = argparse.ArgumentParser(
        description="Manage a Music Assistant development workspace.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print debug output",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- init ---------------------------------------------------------------
    p_init = sub.add_parser("init", help="Create a new workspace")
    p_init.add_argument(
        "--dir",
        default=str(DEFAULT_WORKSPACE),
        help=f"Workspace directory (default: {DEFAULT_WORKSPACE})",
    )
    p_init.add_argument(
        "--providers",
        default=None,
        help="Comma-separated list of provider domains to install",
    )
    p_init.add_argument(
        "--all",
        action="store_true",
        help="Install all non-server_fork providers",
    )
    p_init.set_defaults(func=cmd_init)

    # -- update -------------------------------------------------------------
    p_update = sub.add_parser("update", help="Pull latest code and reinstall deps")
    p_update.add_argument("--dir", default=str(DEFAULT_WORKSPACE))
    p_update.set_defaults(func=cmd_update)

    # -- add ----------------------------------------------------------------
    p_add = sub.add_parser("add", help="Add a provider to an existing workspace")
    p_add.add_argument("domain", help="Provider domain name from providers.yml")
    p_add.add_argument("--dir", default=str(DEFAULT_WORKSPACE))
    p_add.set_defaults(func=cmd_add)

    # -- status -------------------------------------------------------------
    p_status = sub.add_parser("status", help="Show workspace status")
    p_status.add_argument("--dir", default=str(DEFAULT_WORKSPACE))
    p_status.set_defaults(func=cmd_status)

    # -- run ----------------------------------------------------------------
    p_run = sub.add_parser("run", help="Start Music Assistant server")
    p_run.add_argument("--dir", default=str(DEFAULT_WORKSPACE))
    p_run.add_argument(
        "--log-level",
        default="debug",
        help="Log level (default: debug)",
    )
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    VERBOSE = args.verbose
    args.func(args)


if __name__ == "__main__":
    main()
