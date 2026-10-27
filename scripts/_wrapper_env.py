"""Shared Jinja2 environment for rendering ``wrappers/`` templates.

``distribute.py``, ``render_for_provider.py`` and ``validate_templates.py``
all render the same templates, so they build the environment here. On top of
the plain loader it exposes the upstream guidance mirror
(``upstream-guidance/``, see ``sync_upstream_guidance.py``):

- ``upstream_file('<source>/<path>')`` returns a mirrored file's text. Jinja
  does not re-parse the returned string, so upstream ``{{`` is safe.
- ``| demote_headings`` pushes every Markdown heading one level down so an
  upstream document can be embedded under one of our headings.
- ``| strip_title`` drops a leading ``# Title`` line.
- ``| strip_frontmatter`` / ``| frontmatter`` split a YAML front-matter block
  (``---`` ... ``---``) from the body.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO_ROOT = Path(__file__).parent.parent
WRAPPERS_DIR = REPO_ROOT / "wrappers"
GUIDANCE_DIR = REPO_ROOT / "upstream-guidance"

_HEADING_RE = re.compile(r"^(#{1,5}) ")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TITLE_RE = re.compile(r"\A# [^\n]*\n")
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def upstream_file(path: str) -> str:
    """
    Return the text of a mirrored upstream file.

    :param path: Mirror key, ``<source>/<path>`` (e.g. ``server/AGENTS.md``).
    """
    target = (GUIDANCE_DIR / path).resolve()
    if GUIDANCE_DIR.resolve() not in target.parents or not target.is_file():
        raise FileNotFoundError(f"upstream-guidance/{path} is not mirrored")
    return target.read_text(encoding="utf-8")


def demote_headings(text: str) -> str:
    """Return Markdown with every heading outside code fences one level deeper."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            line = _HEADING_RE.sub(lambda m: f"#{m.group(1)} ", line, count=1)
        out.append(line)
    return "".join(out)


def strip_title(text: str) -> str:
    """Return the text without a leading level-1 heading line."""
    return _TITLE_RE.sub("", text, count=1).lstrip("\n")


def strip_frontmatter(text: str) -> str:
    """Return the text without its leading YAML front-matter block."""
    return _FRONTMATTER_RE.sub("", text, count=1).lstrip("\n")


def frontmatter(text: str) -> str:
    """Return only the leading YAML front-matter block, delimiters included."""
    match = _FRONTMATTER_RE.match(text)
    return match.group(0) if match else ""


def make_env(*, keep_trailing_newline: bool = True) -> Environment:
    """Return the wrapper-template environment with the upstream helpers."""
    env = Environment(
        loader=FileSystemLoader(str(WRAPPERS_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=keep_trailing_newline,
    )
    env.globals["upstream_file"] = upstream_file
    env.filters["demote_headings"] = demote_headings
    env.filters["strip_title"] = strip_title
    env.filters["strip_frontmatter"] = strip_frontmatter
    env.filters["frontmatter"] = frontmatter
    return env
