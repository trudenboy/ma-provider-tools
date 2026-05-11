#!/usr/bin/env python3
"""Validate `providers.yml` against `schemas/providers.schema.json`.

Exits 1 on the first schema violation with the JSON Pointer of the
offending value, the failing rule, and the validator's message.

Run locally:
    python3 scripts/validate_providers_yml.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).parent.parent
PROVIDERS_FILE = REPO_ROOT / "providers.yml"
SCHEMA_FILE = REPO_ROOT / "schemas" / "providers.schema.json"


def main() -> int:
    if not PROVIDERS_FILE.is_file():
        print(f"ERROR: {PROVIDERS_FILE} not found", file=sys.stderr)
        return 2
    if not SCHEMA_FILE.is_file():
        print(f"ERROR: {SCHEMA_FILE} not found", file=sys.stderr)
        return 2

    data = yaml.safe_load(PROVIDERS_FILE.read_text())
    schema = json.loads(SCHEMA_FILE.read_text())

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))

    if not errors:
        n = len(data.get("providers", []))
        print(f"validate-providers-yml: {n} providers OK")
        return 0

    for err in errors:
        pointer = "/" + "/".join(str(p) for p in err.absolute_path)
        print(
            f"ERROR at {pointer} (rule: {err.validator}): {err.message}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
