#!/usr/bin/env python3
"""Render selected wrapper templates for a single provider domain.

Used by `reusable-check-config-sync.yml` to produce the expected
`ruff.toml` / `pyproject.toml` for a provider so CI can diff them
against the live files in the provider repo.

Usage:
    python3 scripts/render_for_provider.py \\
        --domain msx_bridge \\
        --out-dir _expected \\
        ruff.toml.j2 pyproject.toml.j2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO_ROOT = Path(__file__).parent.parent
WRAPPERS = REPO_ROOT / "wrappers"
PROVIDERS_FILE = REPO_ROOT / "providers.yml"


def build_context(domain: str) -> dict:
    registry = yaml.safe_load(PROVIDERS_FILE.read_text())
    providers = registry["providers"]
    provider = next((p for p in providers if p["domain"] == domain), None)
    if provider is None:
        raise SystemExit(f"Provider {domain!r} not found in providers.yml")
    return {
        "domain": provider["domain"],
        "display_name": provider.get("display_name", ""),
        "manifest_path": provider.get("manifest_path", ""),
        "provider_path": provider.get("provider_path", ""),
        "provider_type": provider.get("provider_type", ""),
        "locale": provider.get("locale", "en"),
        "repo": provider["repo"],
        "default_branch": provider["default_branch"],
        "service_url": provider.get("service_url", ""),
        "auth_method": provider.get("auth_method", ""),
        "max_quality": provider.get("max_quality", ""),
        "features": provider.get("features", []),
        "codespell_ignore_words": provider.get("codespell_ignore_words", ""),
        "python_version": provider.get("python_version", "3.12"),
        "runtime_dependencies": provider.get("runtime_dependencies", []),
        "extra_test_dependencies": provider.get("extra_test_dependencies", []),
        "all_providers": [
            p for p in providers if p.get("provider_type") != "server_fork"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--domain", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "templates",
        nargs="+",
        help="Template names relative to wrappers/ (e.g. ruff.toml.j2)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(WRAPPERS)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    ctx = build_context(args.domain)

    for tpl in args.templates:
        rendered = env.get_template(tpl).render(**ctx)
        out_name = tpl[:-3] if tpl.endswith(".j2") else tpl
        (out_dir / out_name).write_text(rendered)
        print(f"Rendered {tpl} -> {out_dir / out_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
