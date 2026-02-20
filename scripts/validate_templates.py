#!/usr/bin/env python3
"""Validate that all Jinja2 wrapper templates render without errors.

Checks:
- No Jinja2 syntax errors
- Rendered output ends with exactly one trailing newline (no double-newline at EOF)
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

try:
    from jinja2 import (
        Environment,
        FileSystemLoader,
        StrictUndefined,
        TemplateSyntaxError,
    )
except ImportError:
    print("ERROR: jinja2 not installed. Run: pip install jinja2", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).parent.parent
WRAPPERS_DIR = REPO_ROOT / "wrappers"
PROVIDERS_FILE = REPO_ROOT / "providers.yml"


def main() -> int:
    registry = yaml.safe_load(PROVIDERS_FILE.read_text())
    providers = registry.get("providers", [])

    # Use the first fully-specified provider as render context
    base = next((p for p in providers if p.get("manifest_path")), providers[0])
    context = {
        "domain": base["domain"],
        "manifest_path": base.get("manifest_path", ""),
        "provider_path": base.get("provider_path", ""),
        "provider_type": base.get("provider_type", ""),
    }

    env = Environment(
        loader=FileSystemLoader(str(WRAPPERS_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    templates = sorted(WRAPPERS_DIR.glob("*.j2"))
    errors: list[str] = []

    for tpl_path in templates:
        try:
            out = env.get_template(tpl_path.name).render(**context)
        except TemplateSyntaxError as e:
            errors.append(f"{tpl_path.name}: Jinja2 syntax error — {e}")
            continue
        except Exception as e:
            errors.append(f"{tpl_path.name}: render error — {e}")
            continue

        if not out.endswith("\n"):
            errors.append(f"{tpl_path.name}: missing trailing newline")
        elif out.endswith("\n\n"):
            errors.append(
                f"{tpl_path.name}: trailing blank line (ends with \\n\\n) — use {{%- endraw %}} to strip it"
            )

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print(f"validate-templates: {len(templates)} templates OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
