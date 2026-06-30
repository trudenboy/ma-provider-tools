#!/usr/bin/env python3
"""Single source of truth for the provider-repo <-> upstream path/import transform.

Forward  = provider repo layout  -> music-assistant/server layout
Reverse  = music-assistant/server layout -> provider repo layout

Path mapping:
    <provider_path>           <-> music_assistant/providers/<domain>/
    tests/                    <-> tests/providers/<domain>/

Content rewrite (TEST FILES ONLY — provider source uses relative imports):
    from provider.            <-> from music_assistant.providers.<domain>.
    from provider import      <-> from music_assistant.providers.<domain> import
    "provider.                <-> "music_assistant.providers.<domain>.
"""

from __future__ import annotations

import sys

TESTS_SRC = "tests/"


def _upstream_root(domain: str) -> str:
    return f"music_assistant/providers/{domain}/"


def _upstream_tests(domain: str) -> str:
    return f"tests/providers/{domain}/"


def _norm_provider_path(provider_path: str) -> str:
    return provider_path if provider_path.endswith("/") else provider_path + "/"


def is_test_path(rel_path: str) -> bool:
    return (
        rel_path.startswith(TESTS_SRC)
        or "/tests/providers/" in ("/" + rel_path)
        or rel_path.startswith("tests/providers/")
    )


def forward_path(rel_path: str, domain: str, provider_path: str) -> str | None:
    pp = _norm_provider_path(provider_path)
    if rel_path.startswith(pp):
        return _upstream_root(domain) + rel_path[len(pp) :]
    if rel_path.startswith(TESTS_SRC):
        return _upstream_tests(domain) + rel_path[len(TESTS_SRC) :]
    return None


def reverse_path(rel_path: str, domain: str, provider_path: str) -> str | None:
    pp = _norm_provider_path(provider_path)
    root = _upstream_root(domain)
    troot = _upstream_tests(domain)
    if rel_path.startswith(troot):
        return TESTS_SRC + rel_path[len(troot) :]
    if rel_path.startswith(root):
        return pp + rel_path[len(root) :]
    return None


def _content_rules(domain: str) -> list[tuple[str, str]]:
    """(provider-side, upstream-side) string pairs, longest-first."""
    base = f"music_assistant.providers.{domain}"
    return [
        ("from provider import", f"from music_assistant.providers.{domain} import"),
        ("from provider.", f"from {base}."),
        ('"provider.', f'"{base}.'),
    ]


def _rewrite(text: str, rules: list[tuple[str, str]], *, forward: bool) -> str:
    for prov, ups in rules:
        text = text.replace(prov, ups) if forward else text.replace(ups, prov)
    return text


def forward_content(rel_path: str, text: str, domain: str) -> str:
    if not _is_test_file(rel_path):
        return text
    return _rewrite(text, _content_rules(domain), forward=True)


def reverse_content(rel_path: str, text: str, domain: str) -> str:
    if not _is_test_file(rel_path):
        return text
    return _rewrite(text, _content_rules(domain), forward=False)


def _is_test_file(rel_path: str) -> bool:
    return rel_path.startswith("tests/") and rel_path.endswith(".py")


def _strip_ab(path: str) -> str:
    return path[2:] if path[:2] in ("a/", "b/") else path


def reverse_diff(patch_text: str, domain: str, provider_path: str) -> str:
    """Rewrite a unified diff from upstream layout to provider-repo layout.

    - Splits into per-file sections on `diff --git`.
    - Drops sections whose path maps outside our two roots (reverse_path None).
    - Rewrites `diff --git`, `---`, `+++`, `rename from/to` path lines.
    - For test files, rewrites the import strings on context/added/removed
      content lines (but never on the +++/---/@@ marker lines).
    """
    rules = _content_rules(domain)
    out_sections: list[str] = []
    lines = patch_text.splitlines(keepends=True)
    sections: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        if ln.startswith("diff --git "):
            if cur:
                sections.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        sections.append(cur)

    for sec in sections:
        # Identify the upstream path from the diff --git header.
        header = sec[0]
        parts = header.split()
        # parts: ["diff", "--git", "a/<path>", "b/<path>"]
        up_path = _strip_ab(parts[3]) if len(parts) >= 4 else _strip_ab(parts[-1])
        new_path = reverse_path(up_path, domain, provider_path)
        if new_path is None:
            continue  # foreign file -> drop
        test_file = new_path.startswith("tests/") and new_path.endswith(".py")
        new_sec: list[str] = []
        for ln in sec:
            if ln.startswith("diff --git "):
                a = reverse_path(_strip_ab(parts[2]), domain, provider_path)
                b = reverse_path(_strip_ab(parts[3]), domain, provider_path)
                new_sec.append(f"diff --git a/{a} b/{b}\n")
            elif ln.startswith("--- "):
                tail = ln[4:].rstrip("\n")
                mapped = (
                    "/dev/null"
                    if tail == "/dev/null"
                    else "a/"
                    + (
                        reverse_path(_strip_ab(tail), domain, provider_path)
                        or _strip_ab(tail)
                    )
                )
                new_sec.append(f"--- {mapped}\n")
            elif ln.startswith("+++ "):
                tail = ln[4:].rstrip("\n")
                mapped = (
                    "/dev/null"
                    if tail == "/dev/null"
                    else "b/"
                    + (
                        reverse_path(_strip_ab(tail), domain, provider_path)
                        or _strip_ab(tail)
                    )
                )
                new_sec.append(f"+++ {mapped}\n")
            elif ln.startswith(
                ("rename from ", "rename to ", "copy from ", "copy to ")
            ):
                kw, _, p = ln.rstrip("\n").partition(" ")
                # kw is "rename"/"copy"; re-split properly:
                prefix = ln[: ln.index(" ", ln.index(" ") + 1) + 1]
                old = ln[len(prefix) :].rstrip("\n")
                new_sec.append(
                    prefix + (reverse_path(old, domain, provider_path) or old) + "\n"
                )
            elif (
                test_file
                and ln[:1] in (" ", "+", "-")
                and not ln.startswith(("+++", "---"))
            ):
                marker, body = ln[0], ln[1:]
                new_sec.append(marker + _rewrite(body, rules, forward=False))
            else:
                new_sec.append(ln)
        out_sections.append("".join(new_sec))

    return "".join(out_sections)


def _main(argv: list[str]) -> int:
    """CLI used by the drift-guard test and ad-hoc checks.

    Usage:
        _transform.py reverse-diff <domain> <provider_path>   (stdin -> stdout)
        _transform.py forward-test-content <domain>           (stdin -> stdout)
    """
    if len(argv) >= 2 and argv[0] == "reverse-diff":
        domain, provider_path = argv[1], (argv[2] if len(argv) > 2 else "provider/")
        sys.stdout.write(reverse_diff(sys.stdin.read(), domain, provider_path))
        return 0
    if len(argv) >= 2 and argv[0] == "forward-test-content":
        domain = argv[1]
        sys.stdout.write(forward_content("tests/x.py", sys.stdin.read(), domain))
        return 0
    print(
        "usage: _transform.py {reverse-diff|forward-test-content} ...", file=sys.stderr
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
