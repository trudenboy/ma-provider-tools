#!/usr/bin/env python3
"""Single source of truth for the provider-repo <-> upstream path/import transform.

Forward  = provider repo layout  -> music-assistant/server layout
Reverse  = music-assistant/server layout -> provider repo layout

Path mapping:
    <provider_path>           <-> music_assistant/providers/<domain>/
    tests/                    <-> tests/providers/<domain>/

Content rewrite (TEST FILES ONLY — provider source uses relative imports).
This is the canonical rule set; both forward `sed` blocks
(reusable-sync-to-fork.yml and upstream-pr.yml.j2) are pinned to it by
tests/test_forward_sed_parity.py.

    from provider.            <-> from music_assistant.providers.<domain>.
    from provider import      <-> from music_assistant.providers.<domain> import
    import provider.          <-> import music_assistant.providers.<domain>.
    import provider as X      <-> import music_assistant.providers.<domain> as X
    import provider           <-> import music_assistant.providers.<domain>
    "provider.                <-> "music_assistant.providers.<domain>.
    'provider.                <-> 'music_assistant.providers.<domain>.
"""

from __future__ import annotations

import re
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


def _rules(domain: str, *, forward: bool) -> list[tuple[re.Pattern[str], str]]:
    """Compiled (pattern, replacement) rules for one direction.

    Mirrors the `sed` expressions in upstream-pr.yml.j2 /
    reusable-sync-to-fork.yml: word boundaries (\\b) and end-of-line ($,
    re.MULTILINE) so the bare/aliased `import provider` forms don't over-match
    the dotted form or each other. Most-specific first. The package name is
    regex-escaped on the side it appears as a pattern, so it round-trips:
    reverse(forward(x)) == x.
    """
    pkg = f"music_assistant.providers.{domain}"
    pkg_re = re.escape(pkg)
    # (provider-side regex, provider-side text, upstream-side regex, upstream text)
    pairs = [
        (
            r"\bfrom provider import\b",
            "from provider import",
            rf"\bfrom {pkg_re} import\b",
            f"from {pkg} import",
        ),
        (r"\bfrom provider\.", "from provider.", rf"\bfrom {pkg_re}\.", f"from {pkg}."),
        (
            r"\bimport provider(\s+as\s)",
            r"import provider\1",
            rf"\bimport {pkg_re}(\s+as\s)",
            rf"import {pkg}\1",
        ),
        (
            r"\bimport provider\.",
            "import provider.",
            rf"\bimport {pkg_re}\.",
            f"import {pkg}.",
        ),
        (
            r"\bimport provider$",
            "import provider",
            rf"\bimport {pkg_re}$",
            f"import {pkg}",
        ),
        (r'"provider\.', '"provider.', rf'"{pkg_re}\.', f'"{pkg}.'),
        (r"'provider\.", "'provider.", rf"'{pkg_re}\.", f"'{pkg}."),
    ]
    rules = []
    for prov_pat, prov_txt, ups_pat, ups_txt in pairs:
        if forward:
            rules.append((re.compile(prov_pat, re.MULTILINE), ups_txt))
        else:
            # repl is the provider side; keep the backreference for the aliased
            # rule (prov_txt carries \1), plain text otherwise.
            repl = prov_txt if r"\1" in prov_txt else prov_txt
            rules.append((re.compile(ups_pat, re.MULTILINE), repl))
    return rules


def _rewrite(text: str, domain: str, *, forward: bool) -> str:
    for pattern, repl in _rules(domain, forward=forward):
        text = pattern.sub(repl, text)
    return text


def forward_content(rel_path: str, text: str, domain: str) -> str:
    if not _is_test_file(rel_path):
        return text
    return _rewrite(text, domain, forward=True)


def reverse_content(rel_path: str, text: str, domain: str) -> str:
    if not _is_test_file(rel_path):
        return text
    return _rewrite(text, domain, forward=False)


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
    rev_rules = _rules(domain, forward=False)
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
                for pattern, repl in rev_rules:
                    body = pattern.sub(repl, body)
                new_sec.append(marker + body)
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
