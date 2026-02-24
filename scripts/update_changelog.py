#!/usr/bin/env python3
"""Insert a new entry into CHANGELOG.md before the auto-generation marker."""

import sys
from pathlib import Path

version, date, notes_file = sys.argv[1], sys.argv[2], sys.argv[3]
notes = Path(notes_file).read_text().rstrip()
marker = "<!-- changelog entries will be added here by release workflow -->"
entry = f"## [{version}] - {date}\n\n{notes}\n\n---\n\n"

path = Path("CHANGELOG.md")
content = path.read_text()
if marker not in content:
    print("WARNING: marker not found in CHANGELOG.md, skipping update", file=sys.stderr)
    sys.exit(0)
path.write_text(content.replace(marker, entry + marker, 1))
print(f"Updated CHANGELOG.md for v{version}")
