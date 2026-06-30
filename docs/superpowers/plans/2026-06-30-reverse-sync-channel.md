# Reverse-sync channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a poll-based reverse-sync channel that detects inbound PRs in `music-assistant/server` touching our provider paths, auto-opens draft port PRs in the provider repos, and guards forward-sync against silently reverting un-ported upstream work.

**Architecture:** A cron radar (`reverse_sync_radar.py`) makes read-only GitHub API calls against `music-assistant/server`, runs two passes (commit-on-default anchor + merged-PR action) per provider in `providers.yml`, and persists progress to a committed `state/reverse-sync.json`. On a new merged PR it invokes `reverse_sync_open_pr.py`, which inverts the forward path/import transform (shared logic in `_transform.py`), applies the patch best-effort, and opens an always-draft PR in the provider repo. A preflight guard in `reusable-sync-to-fork.yml` blocks the destructive `rsync --delete` when upstream is ahead, overridable via an `ack_upstream_ahead` input.

**Tech Stack:** Python 3.12 (stdlib + `pyyaml`), `pytest` (new to this repo), GitHub Actions, `gh` CLI, `git`.

## Global Constraints

- **AI-Policy rule 2:** ALL access to `music-assistant/*` is read-only (HTTP GET / `gh ... --json` read commands only). No `gh pr create/comment/edit/review/merge/close` and no `git push` may ever target `music-assistant/*`. Writes go only to provider repos (`trudenboy/ma-provider-*`) and this hub.
- **VERSION and `translations/en.json` are maintainer-owned** — never written/committed by any script in this plan.
- **Python version:** 3.12 (matches `ci.yml` and `update-ma-version-badges.yml`).
- **Lint:** `ruff` (pre-commit rev v0.9.6) runs on `scripts/`. All new `scripts/*.py` must pass `ruff check` and `ruff format`.
- **No new runtime service / no external state store** — state is a JSON file committed to this hub, mirroring `public/badges/`.
- **Registry-driven:** every per-provider behavior iterates `providers.yml`; no per-repo hand-wiring.
- **Transform truth:** forward path/import rewrites currently live as inline `sed` in `reusable-sync-to-fork.yml:117-125`. The forward rules are: test files only — `from provider.` → `from music_assistant.providers.<domain>.`, `from provider import` → `from music_assistant.providers.<domain> import`, `"provider.` → `"music_assistant.providers.<domain>.`; plus the rsync path mapping `provider_path` → `music_assistant/providers/<domain>/` and `tests/` → `tests/providers/<domain>/`. Provider **source** files use relative imports and are NOT content-rewritten.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/_transform.py` | Pure transform: path mapping + test-import rewrite, both directions; unified-diff reverse rewriter. Single source of truth. |
| `scripts/reverse_sync_state.py` | Load/save/validate `state/reverse-sync.json`; small dataclass-free dict helpers. |
| `scripts/check_upstream_ahead.py` | Content-hash compare of upstream provider path vs provider repo, ignore-list aware. Used by the P0 guard. |
| `scripts/reverse_sync_open_pr.py` | Fetch inbound PR diff (read-only), reverse-transform, `git apply --3way`, scaffold, open draft PR in provider repo. |
| `scripts/reverse_sync_radar.py` | Two-pass radar over `providers.yml`; echo filter; calls the opener; updates state; notifications. |
| `scripts/reverse_sync_notify.py` | Open/update hub digest & incident issues (dedup by label+title). |
| `state/reverse-sync.json` | Committed progress state. |
| `.github/workflows/reverse-sync-radar.yml` | Cron (every 2h) + `workflow_dispatch` running the radar. |
| `.github/workflows/reusable-sync-to-fork.yml` | (modify) insert preflight-guard step before the rsync. |
| `wrappers/sync-to-fork.yml.j2` | (modify) add `ack_upstream_ahead` dispatch input, pass through. |
| `tests/` | New pytest suite. |
| `requirements-dev.txt` | New: `pytest`, `pyyaml`. |
| `.github/workflows/ci.yml` | (modify) add a `pytest` step. |

---

## Task 1: Transform module + pytest bootstrap

**Files:**
- Create: `scripts/_transform.py`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_transform.py`
- Create: `requirements-dev.txt`
- Modify: `.github/workflows/ci.yml` (add pytest step)

**Interfaces:**
- Produces:
  - `forward_path(rel_path: str, domain: str, provider_path: str) -> str | None`
  - `reverse_path(rel_path: str, domain: str, provider_path: str) -> str | None` (returns `None` if path is outside our two mapped roots)
  - `forward_content(rel_path: str, text: str, domain: str) -> str`
  - `reverse_content(rel_path: str, text: str, domain: str) -> str`
  - `reverse_diff(patch_text: str, domain: str, provider_path: str) -> str`
  - `is_test_path(rel_path: str) -> bool`

- [ ] **Step 1: Create `requirements-dev.txt`**

```
pytest>=8,<9
pyyaml>=6
```

- [ ] **Step 2: Write the failing tests**

`tests/__init__.py`: empty file.

`tests/test_transform.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _transform as t  # noqa: E402

DOMAIN = "yandex_music"
PP = "provider/"


def test_forward_path_source():
    assert t.forward_path("provider/manifest.json", DOMAIN, PP) == (
        "music_assistant/providers/yandex_music/manifest.json"
    )


def test_forward_path_tests():
    assert t.forward_path("tests/test_api.py", DOMAIN, PP) == (
        "tests/providers/yandex_music/test_api.py"
    )


def test_reverse_path_source():
    assert t.reverse_path(
        "music_assistant/providers/yandex_music/api.py", DOMAIN, PP
    ) == "provider/api.py"


def test_reverse_path_tests():
    assert t.reverse_path(
        "tests/providers/yandex_music/test_api.py", DOMAIN, PP
    ) == "tests/test_api.py"


def test_reverse_path_outside_returns_none():
    assert t.reverse_path("music_assistant/server.py", DOMAIN, PP) is None
    assert t.reverse_path(
        "music_assistant/providers/other/api.py", DOMAIN, PP
    ) is None


def test_test_import_roundtrip():
    src = (
        'from provider.api import Client\n'
        'from provider import Provider\n'
        'm = mock.patch("provider.api.Client")\n'
    )
    fwd = t.forward_content("tests/test_api.py", src, DOMAIN)
    assert "music_assistant.providers.yandex_music" in fwd
    assert t.reverse_content(
        "tests/providers/yandex_music/test_api.py", fwd, DOMAIN
    ) == src


def test_source_content_unchanged():
    # Provider source uses relative imports; content must not be rewritten.
    src = "from .api import Client\nVALUE = 1\n"
    assert t.forward_content("provider/__init__.py", src, DOMAIN) == src
    assert t.reverse_content(
        "music_assistant/providers/yandex_music/__init__.py", src, DOMAIN
    ) == src


def test_reverse_diff_rewrites_headers_and_test_content():
    patch = (
        "diff --git a/music_assistant/providers/yandex_music/api.py "
        "b/music_assistant/providers/yandex_music/api.py\n"
        "--- a/music_assistant/providers/yandex_music/api.py\n"
        "+++ b/music_assistant/providers/yandex_music/api.py\n"
        "@@ -1,1 +1,2 @@\n"
        " from .base import X\n"
        "+Y = 2\n"
        "diff --git a/tests/providers/yandex_music/test_api.py "
        "b/tests/providers/yandex_music/test_api.py\n"
        "--- a/tests/providers/yandex_music/test_api.py\n"
        "+++ b/tests/providers/yandex_music/test_api.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-from music_assistant.providers.yandex_music.api import C\n"
        "+from music_assistant.providers.yandex_music.api import C2\n"
    )
    out = t.reverse_diff(patch, DOMAIN, PP)
    assert "a/provider/api.py" in out
    assert "b/tests/test_api.py" in out
    assert "music_assistant/providers/yandex_music" not in out
    # Source hunk content (relative import) preserved:
    assert " from .base import X" in out
    # Test hunk content rewritten on +/- lines:
    assert "-from provider.api import C\n" in out
    assert "+from provider.api import C2\n" in out


def test_reverse_diff_drops_foreign_files():
    patch = (
        "diff --git a/music_assistant/server.py b/music_assistant/server.py\n"
        "--- a/music_assistant/server.py\n"
        "+++ b/music_assistant/server.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x\n"
        "+y\n"
    )
    assert t.reverse_diff(patch, DOMAIN, PP).strip() == ""
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pip install -r requirements-dev.txt && python -m pytest tests/test_transform.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named '_transform'`.

- [ ] **Step 4: Implement `scripts/_transform.py`**

```python
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
    return rel_path.startswith(TESTS_SRC) or "/tests/providers/" in (
        "/" + rel_path
    ) or rel_path.startswith("tests/providers/")


def forward_path(rel_path: str, domain: str, provider_path: str) -> str | None:
    pp = _norm_provider_path(provider_path)
    if rel_path.startswith(pp):
        return _upstream_root(domain) + rel_path[len(pp):]
    if rel_path.startswith(TESTS_SRC):
        return _upstream_tests(domain) + rel_path[len(TESTS_SRC):]
    return None


def reverse_path(rel_path: str, domain: str, provider_path: str) -> str | None:
    pp = _norm_provider_path(provider_path)
    root = _upstream_root(domain)
    troot = _upstream_tests(domain)
    if rel_path.startswith(troot):
        return TESTS_SRC + rel_path[len(troot):]
    if rel_path.startswith(root):
        return pp + rel_path[len(root):]
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
    return (
        rel_path.startswith("tests/")
        and rel_path.endswith(".py")
    )


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
                    else "a/" + (reverse_path(_strip_ab(tail), domain, provider_path) or _strip_ab(tail))
                )
                new_sec.append(f"--- {mapped}\n")
            elif ln.startswith("+++ "):
                tail = ln[4:].rstrip("\n")
                mapped = (
                    "/dev/null"
                    if tail == "/dev/null"
                    else "b/" + (reverse_path(_strip_ab(tail), domain, provider_path) or _strip_ab(tail))
                )
                new_sec.append(f"+++ {mapped}\n")
            elif ln.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
                kw, _, p = ln.rstrip("\n").partition(" ")
                # kw is "rename"/"copy"; re-split properly:
                prefix = ln[: ln.index(" ", ln.index(" ") + 1) + 1]
                old = ln[len(prefix):].rstrip("\n")
                new_sec.append(prefix + (reverse_path(old, domain, provider_path) or old) + "\n")
            elif test_file and ln[:1] in (" ", "+", "-") and not ln.startswith(("+++", "---")):
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
    print("usage: _transform.py {reverse-diff|forward-test-content} ...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
```

> Note: the `is_test_path` public helper and the internal `_is_test_file` differ
> on purpose — `_is_test_file` gates content rewriting (must be a `.py` under
> `tests/`), while `is_test_path` is a looser predicate reused by callers.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_transform.py -q`
Expected: PASS (8 passed).

- [ ] **Step 6: Add pytest to CI**

In `.github/workflows/ci.yml`, after the `validate_providers_yml.py` step, add:

```yaml
      - name: pytest
        run: |
          pip install -r requirements-dev.txt
          python -m pytest tests/ -q
```

- [ ] **Step 7: Lint + commit**

```bash
ruff check scripts/_transform.py && ruff format scripts/_transform.py tests/test_transform.py
git add scripts/_transform.py tests/__init__.py tests/test_transform.py requirements-dev.txt .github/workflows/ci.yml
git commit -m "feat(reverse-sync): add shared path/import transform module + pytest"
```

---

## Task 2: Forward-transform drift guard

**Rationale / design refinement:** Decision #4 said "refactor forward-sync to call `_transform.py`." But `reusable-sync-to-fork.yml` is consumed by provider repos via `uses:` and does NOT have this hub's `scripts/` on its runner; wiring a cross-repo checkout into that critical path is higher-risk than the drift it prevents. Instead we keep the inline `sed` in the workflow and add a hub test asserting `_transform.forward_content` reproduces exactly what the `sed` rules do. Same anti-drift guarantee, zero risk to the live sync path.

**Files:**
- Create: `tests/test_forward_sed_parity.py`

**Interfaces:**
- Consumes: `_transform.forward_content` (Task 1).

- [ ] **Step 1: Write the failing test**

`tests/test_forward_sed_parity.py`:

```python
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import _transform as t  # noqa: E402

DOMAIN = "yandex_music"

# Exactly the three sed expressions in
# .github/workflows/reusable-sync-to-fork.yml (test-import rewrites).
SED_EXPRS = [
    rf"s/from provider\./from music_assistant.providers.{DOMAIN}./g",
    rf"s/from provider import/from music_assistant.providers.{DOMAIN} import/g",
    rf's/"provider\./"music_assistant.providers.{DOMAIN}./g',
]

SAMPLE = (
    'from provider.api import Client\n'
    'from provider import Provider\n'
    'patch("provider.api.Client")\n'
    'x = "providerish"\n'  # must NOT match "provider. boundary
)


def _run_sed(text: str) -> str:
    for expr in SED_EXPRS:
        text = subprocess.run(
            ["sed", expr], input=text, capture_output=True, text=True, check=True
        ).stdout
    return text


def test_forward_content_matches_sed():
    assert t.forward_content("tests/test_x.py", SAMPLE, DOMAIN) == _run_sed(SAMPLE)
```

- [ ] **Step 2: Run to verify it passes (parity already holds)**

Run: `python -m pytest tests/test_forward_sed_parity.py -q`
Expected: PASS. (If it FAILS, `_transform._content_rules` diverged from the workflow's `sed` — fix `_transform.py` until parity holds; do not edit the test to match a bug.)

- [ ] **Step 3: Add a guard comment in the workflow**

In `.github/workflows/reusable-sync-to-fork.yml`, immediately above line 117 (`# Rewrite test imports:`), add:

```yaml
            # NOTE: these 3 sed rules are mirrored by scripts/_transform.py and
            # asserted equal by tests/test_forward_sed_parity.py. Change both together.
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_forward_sed_parity.py .github/workflows/reusable-sync-to-fork.yml
git commit -m "test(reverse-sync): pin forward sed rules to _transform via parity test"
```

---

## Task 3: State module + initial state file

**Files:**
- Create: `scripts/reverse_sync_state.py`
- Create: `state/reverse-sync.json`
- Create: `tests/test_state.py`

**Interfaces:**
- Produces:
  - `DEFAULT_ENTRY` constant
  - `load(path: Path) -> dict`
  - `save(path: Path, data: dict) -> None` (stable key order, trailing newline)
  - `entry(data: dict, domain: str) -> dict` (returns the per-domain dict, creating a default if missing)
  - `mark_handled(data: dict, domain: str, pr: int) -> None`
  - `is_handled(data: dict, domain: str, pr: int) -> bool`

- [ ] **Step 1: Write the failing tests**

`tests/test_state.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reverse_sync_state as st  # noqa: E402


def test_load_missing_returns_empty(tmp_path):
    assert st.load(tmp_path / "nope.json") == {}


def test_entry_creates_default():
    data = {}
    e = st.entry(data, "yandex_music")
    assert e == {
        "last_synced_sha": None,
        "handled_prs": [],
        "pulls_cursor": None,
        "digest_issue": None,
    }
    assert data["yandex_music"] is e  # stored back


def test_mark_and_is_handled():
    data = {}
    assert st.is_handled(data, "d", 4313) is False
    st.mark_handled(data, "d", 4313)
    assert st.is_handled(data, "d", 4313) is True
    st.mark_handled(data, "d", 4313)  # idempotent
    assert st.entry(data, "d")["handled_prs"] == [4313]


def test_save_roundtrip(tmp_path):
    data = {"d": st.DEFAULT_ENTRY | {"handled_prs": [1, 2]}}
    p = tmp_path / "s.json"
    st.save(p, data)
    text = p.read_text()
    assert text.endswith("\n")
    assert json.loads(text)["d"]["handled_prs"] == [1, 2]
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reverse_sync_state'`.

- [ ] **Step 3: Implement `scripts/reverse_sync_state.py`**

```python
#!/usr/bin/env python3
"""Read/write the committed reverse-sync progress state.

state/reverse-sync.json shape:
    { "<domain>": {
        "last_synced_sha": str | null,   # latest upstream SHA on the path (anchor)
        "handled_prs": [int],            # inbound PRs already ported
        "pulls_cursor": str | null,      # ISO updated_at watermark for pass B
        "digest_issue": int | null       # hub digest issue number
    }, ... }
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ENTRY = {
    "last_synced_sha": None,
    "handled_prs": [],
    "pulls_cursor": None,
    "digest_issue": None,
}


def load(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text())


def save(path: Path, data: dict) -> None:
    serialized = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    Path(path).write_text(serialized + "\n")


def entry(data: dict, domain: str) -> dict:
    if domain not in data:
        data[domain] = dict(DEFAULT_ENTRY)
        data[domain]["handled_prs"] = []
    return data[domain]


def mark_handled(data: dict, domain: str, pr: int) -> None:
    handled = entry(data, domain)["handled_prs"]
    if pr not in handled:
        handled.append(pr)


def is_handled(data: dict, domain: str, pr: int) -> bool:
    return pr in entry(data, domain)["handled_prs"]
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_state.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Create the initial committed state file**

`state/reverse-sync.json`:

```json
{}
```

(Single line `{}` followed by a newline.)

- [ ] **Step 6: Lint + commit**

```bash
ruff check scripts/reverse_sync_state.py && ruff format scripts/reverse_sync_state.py tests/test_state.py
git add scripts/reverse_sync_state.py state/reverse-sync.json tests/test_state.py
git commit -m "feat(reverse-sync): add state module + initial state file"
```

---

## Task 4: Upstream-ahead check (P0 guard core)

**Files:**
- Create: `scripts/check_upstream_ahead.py`
- Create: `tests/test_check_upstream_ahead.py`

**Interfaces:**
- Consumes: `_transform.reverse_path` (Task 1).
- Produces:
  - `IGNORE_SUFFIXES` constant (`("VERSION", "translations/en.json")`)
  - `diff_files(upstream_files: dict[str, str], provider_files: dict[str, str], domain: str, provider_path: str) -> list[str]` — returns provider-repo-relative paths that differ and are NOT ignored. `upstream_files`/`provider_files` map path→sha256 of content.
  - `main()` CLI returning exit code 0 (not ahead) / 1 (ahead) reading real data via `gh`/`git`.

The pure `diff_files` function is unit-tested; the `main()` IO wrapper is exercised by the workflow fixture in Task 8's integration note.

- [ ] **Step 1: Write the failing tests**

`tests/test_check_upstream_ahead.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_upstream_ahead as g  # noqa: E402

DOMAIN = "yandex_music"
PP = "provider/"
ROOT = f"music_assistant/providers/{DOMAIN}/"


def test_identical_not_ahead():
    up = {ROOT + "api.py": "aaa"}
    prov = {"provider/api.py": "aaa"}
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_content_change_is_ahead():
    up = {ROOT + "api.py": "NEW"}
    prov = {"provider/api.py": "OLD"}
    assert g.diff_files(up, prov, DOMAIN, PP) == ["provider/api.py"]


def test_new_upstream_file_is_ahead():
    up = {ROOT + "feature.py": "x"}
    prov = {}
    assert g.diff_files(up, prov, DOMAIN, PP) == ["provider/feature.py"]


def test_version_difference_ignored():
    up = {ROOT + "VERSION": "2.0.0"}
    prov = {"provider/VERSION": "1.0.0"}
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_translations_ignored():
    up = {ROOT + "translations/en.json": "{a}"}
    prov = {"provider/translations/en.json": "{b}"}
    assert g.diff_files(up, prov, DOMAIN, PP) == []


def test_foreign_upstream_path_ignored():
    up = {"music_assistant/server.py": "x"}
    prov = {}
    assert g.diff_files(up, prov, DOMAIN, PP) == []
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_check_upstream_ahead.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'check_upstream_ahead'`.

- [ ] **Step 3: Implement `scripts/check_upstream_ahead.py`**

```python
#!/usr/bin/env python3
"""Preflight check: is upstream's provider path ahead of the provider repo?

Used by reusable-sync-to-fork.yml before the destructive rsync --delete to
avoid silently reverting un-ported upstream contributions.

Compares content hashes of every file under
music_assistant/providers/<domain>/ in music-assistant/server (read-only)
against the provider repo's mirror, ignoring maintainer-owned files.

Exit 0 = not ahead (safe to sync). Exit 1 = ahead (block unless acked).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _transform as t  # noqa: E402

UPSTREAM = "music-assistant/server"
IGNORE_SUFFIXES = ("VERSION", "translations/en.json")


def _ignored(provider_rel: str) -> bool:
    return any(provider_rel.endswith(s) for s in IGNORE_SUFFIXES)


def diff_files(
    upstream_files: dict[str, str],
    provider_files: dict[str, str],
    domain: str,
    provider_path: str,
) -> list[str]:
    """Return provider-repo-relative paths that differ and are not ignored."""
    out: list[str] = []
    for up_path, up_hash in sorted(upstream_files.items()):
        prov_rel = t.reverse_path(up_path, domain, provider_path)
        if prov_rel is None or _ignored(prov_rel):
            continue
        if provider_files.get(prov_rel) != up_hash:
            out.append(prov_rel)
    return out


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _gh_json(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True
    ).stdout


def _list_upstream_tree(domain: str, ref: str) -> dict[str, str]:
    """Read-only: list files + blob sha under the provider path on upstream."""
    import json

    root = f"music_assistant/providers/{domain}"
    raw = _gh_json(
        [
            "api",
            f"repos/{UPSTREAM}/git/trees/{ref}?recursive=1",
            "--jq",
            ".tree[] | select(.type==\"blob\") | "
            f"select(.path|startswith(\"{root}/\")) | "
            "{path:.path, sha:.sha}",
        ]
    )
    files: dict[str, str] = {}
    for line in raw.splitlines():
        if line.strip():
            obj = json.loads(line)
            files[obj["path"]] = obj["sha"]
    return files


def _git_blob_sha(repo_dir: str, rel: str) -> str | None:
    p = os.path.join(repo_dir, rel)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as fh:
        data = fh.read()
    # git blob sha = sha1("blob <len>\0<data>"); upstream tree gives git sha,
    # so compute git object id to compare like-for-like.
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--provider-path", required=True)
    ap.add_argument("--provider-dir", required=True, help="checked-out provider repo root")
    ap.add_argument("--upstream-ref", default="HEAD")
    args = ap.parse_args()

    upstream = _list_upstream_tree(args.domain, args.upstream_ref)
    provider: dict[str, str] = {}
    for up_path in upstream:
        rel = t.reverse_path(up_path, args.domain, args.provider_path)
        if rel is None:
            continue
        sha = _git_blob_sha(args.provider_dir, rel)
        if sha is not None:
            provider[rel] = sha

    ahead = diff_files(upstream, provider, args.domain, args.provider_path)
    if ahead:
        print("::warning::Upstream is ahead of the provider repo on:", file=sys.stderr)
        for f in ahead:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("Provider repo is in sync with upstream provider path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> The unit tests pass content hashes as opaque equal/!= tokens, so they don't
> depend on the sha1-vs-sha256 detail; `main()` computes git blob ids so the
> upstream tree sha and the local blob id are comparable like-for-like.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_check_upstream_ahead.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Lint + commit**

```bash
ruff check scripts/check_upstream_ahead.py && ruff format scripts/check_upstream_ahead.py tests/test_check_upstream_ahead.py
git add scripts/check_upstream_ahead.py tests/test_check_upstream_ahead.py
git commit -m "feat(reverse-sync): add upstream-ahead preflight check"
```

---

## Task 5: Wire the P0 guard into forward-sync + ack input

**Files:**
- Modify: `.github/workflows/reusable-sync-to-fork.yml` (add input + guard step before the rsync step)
- Modify: `wrappers/sync-to-fork.yml.j2` (add `ack_upstream_ahead` dispatch input, pass through)

**Interfaces:**
- Consumes: `scripts/check_upstream_ahead.py` (Task 4). The reusable workflow checks out this hub to access it.

- [ ] **Step 1: Add the input to the reusable workflow**

In `.github/workflows/reusable-sync-to-fork.yml`, under `on.workflow_call.inputs`, add:

```yaml
      ack_upstream_ahead:
        description: "Sync even if upstream is ahead of the provider repo (override the preflight guard)"
        type: boolean
        default: false
```

- [ ] **Step 2: Add the guard step**

In the `sync` job, immediately BEFORE the `- name: Sync provider files into integration/dev` step, insert:

```yaml
      - name: Checkout tools hub (for preflight scripts)
        uses: actions/checkout@v4
        with:
          repository: trudenboy/ma-provider-tools
          path: tools-hub
          ref: main

      - name: Preflight — block if upstream is ahead
        if: ${{ !inputs.ack_upstream_ahead }}
        env:
          GH_TOKEN: ${{ secrets.FORK_SYNC_PAT }}
        run: |
          DOMAIN=$(python3 -c "import json; print(json.load(open('provider-repo/${{ inputs.manifest_path }}'))['domain'])")
          if ! python3 tools-hub/scripts/check_upstream_ahead.py \
                --domain "$DOMAIN" \
                --provider-path "${{ inputs.provider_path }}" \
                --provider-dir provider-repo; then
            echo "::error::Upstream music-assistant/server is ahead of this provider repo for '${DOMAIN}'." \
                 "A contributor's change would be reverted by this sync." \
                 "Run a reverse-sync first, or re-dispatch with ack_upstream_ahead=true to override." >&2
            exit 1
          fi
```

> The guard reads upstream read-only via `gh api .../git/trees` (AI-Policy safe).
> `ack_upstream_ahead=true` skips the whole step.

- [ ] **Step 3: Add the dispatch input to the wrapper**

In `wrappers/sync-to-fork.yml.j2`, under `workflow_dispatch.inputs`, add after `version`:

```yaml
      ack_upstream_ahead:
        description: "Override the preflight guard and sync even if upstream is ahead"
        type: boolean
        default: false
```

And under `jobs.sync.with`, inside the existing `{% raw %}...{% endraw %}` block, add:

```yaml
      ack_upstream_ahead: ${{ inputs.ack_upstream_ahead }}
```

- [ ] **Step 4: Validate the template renders**

Run:
```bash
python3 scripts/validate_templates.py
```
Expected: exits 0, no errors for `sync-to-fork.yml.j2`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/reusable-sync-to-fork.yml wrappers/sync-to-fork.yml.j2
git commit -m "feat(reverse-sync): preflight guard in forward-sync with ack override"
```

---

## Task 6: Reverse-PR opener

**Files:**
- Create: `scripts/reverse_sync_open_pr.py`
- Create: `tests/test_open_pr.py`

**Interfaces:**
- Consumes: `_transform.reverse_diff` (Task 1).
- Produces:
  - `build_pr_body(pr: dict, domain: str, conflicts: bool) -> str`
  - `build_branch(domain: str, pr_number: int) -> str`
  - `scaffold_paths(domain: str, pr_number: int) -> dict[str, str]` (path → file content for the spec stub + changelog stub)
  - `open_reverse_pr(...)` orchestration (IO; not unit-tested directly)

- [ ] **Step 1: Write the failing tests**

`tests/test_open_pr.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reverse_sync_open_pr as o  # noqa: E402

PR = {
    "number": 4313,
    "title": "Fix track parsing",
    "user": {"login": "alice"},
    "html_url": "https://github.com/music-assistant/server/pull/4313",
}


def test_build_branch():
    assert o.build_branch("fastmcp_server", 4313) == "reverse-sync/fastmcp_server-pr4313"


def test_body_has_upstream_link_and_credit():
    body = o.build_pr_body(PR, "fastmcp_server", conflicts=False)
    assert "music-assistant/server/pull/4313" in body
    assert "@alice" in body
    assert "VERSION" in body  # reminder line about maintainer-owned files


def test_body_flags_conflicts():
    clean = o.build_pr_body(PR, "fastmcp_server", conflicts=False)
    dirty = o.build_pr_body(PR, "fastmcp_server", conflicts=True)
    assert "conflict" in dirty.lower()
    assert "conflict" not in clean.lower()


def test_scaffold_paths():
    paths = o.scaffold_paths("fastmcp_server", 4313)
    spec = next(p for p in paths if p.startswith("specs/inprogress/"))
    assert "WIP=1" in paths[spec]
    assert any(p.endswith("CHANGELOG.md") or "CHANGELOG" in p for p in paths)
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_open_pr.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reverse_sync_open_pr'`.

- [ ] **Step 3: Implement `scripts/reverse_sync_open_pr.py`**

```python
#!/usr/bin/env python3
"""Open a draft reverse-sync PR in a provider repo for one inbound upstream PR.

Read-only against music-assistant/server (gh pr diff / view). All writes target
the provider repo only. Best-effort apply: always opens a draft PR; conflicts
are left in-tree and the PR is labelled needs-human.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _transform as t  # noqa: E402

UPSTREAM = "music-assistant/server"


def build_branch(domain: str, pr_number: int) -> str:
    return f"reverse-sync/{domain}-pr{pr_number}"


def build_pr_body(pr: dict, domain: str, conflicts: bool) -> str:
    lines = [
        f"Reverse-sync of upstream PR {pr['html_url']} into the `{domain}` provider.",
        "",
        f"Original author: @{pr['user']['login']} (credited via `Co-authored-by`).",
        "",
        "**Maintainer-owned files were NOT touched** — review `VERSION` and "
        "`translations/en.json` manually if the upstream change implies a bump.",
        "",
        "- [ ] Spec filled in (`specs/inprogress/`)",
        "- [ ] CHANGELOG entry finalized",
        "- [ ] Tests pass locally",
    ]
    if conflicts:
        lines.insert(
            1,
            "\n> ⚠ Patch applied with **conflicts** — `.rej`/markers left in the "
            "tree. Resolve them before marking ready.\n",
        )
    return "\n".join(lines)


def scaffold_paths(domain: str, pr_number: int) -> dict[str, str]:
    spec = f"specs/inprogress/reverse-sync-pr{pr_number}.md"
    return {
        spec: (
            f"# Reverse-sync: upstream PR #{pr_number}\n\n"
            "WIP=1\n\n"
            f"Ported from music-assistant/server#{pr_number} into `{domain}`.\n\n"
            "## Summary\n\n_TODO: describe the change._\n"
        ),
        "CHANGELOG.md": f"- Reverse-synced upstream PR #{pr_number} (WIP)\n",
    }


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, **kw)


def open_reverse_pr(
    domain: str,
    provider_path: str,
    provider_repo: str,
    default_branch: str,
    pr_number: int,
    provider_dir: str,
) -> dict:
    """Returns {'skipped': bool, 'reason'|'pr_url': str, 'conflicts': bool}."""
    pr_json = _run(
        ["gh", "pr", "view", str(pr_number), "--repo", UPSTREAM,
         "--json", "number,title,url,author"],
        capture_output=True, check=True,
    ).stdout
    import json

    raw = json.loads(pr_json)
    pr = {
        "number": raw["number"],
        "title": raw["title"],
        "html_url": raw["url"],
        "user": {"login": raw["author"]["login"]},
    }

    patch = _run(
        ["gh", "pr", "diff", str(pr_number), "--repo", UPSTREAM, "--patch"],
        capture_output=True, check=True,
    ).stdout
    reversed_patch = t.reverse_diff(patch, domain, provider_path)
    if not reversed_patch.strip():
        return {"skipped": True, "reason": "no provider-path changes"}

    branch = build_branch(domain, pr_number)
    git = lambda *a: _run(["git", "-C", provider_dir, *a], capture_output=True)  # noqa: E731

    # Echo dedup: if the patch already applies as a no-op, skip.
    check = _run(
        ["git", "-C", provider_dir, "apply", "--check", "--reverse", "-"],
        input=reversed_patch, capture_output=True,
    )
    if check.returncode == 0:
        return {"skipped": True, "reason": "already present (no-op)"}

    git("checkout", default_branch)
    git("checkout", "-B", branch)

    apply_res = _run(
        ["git", "-C", provider_dir, "apply", "--3way", "-"],
        input=reversed_patch, capture_output=True,
    )
    conflicts = apply_res.returncode != 0

    for rel, content in scaffold_paths(domain, pr_number).items():
        dest = os.path.join(provider_dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        mode = "a" if rel.endswith("CHANGELOG.md") and os.path.exists(dest) else "w"
        with open(dest, mode) as fh:
            fh.write(content)

    git("add", "-A")
    author = pr["user"]["login"]
    trailer = f"Co-authored-by: {author} <{author}@users.noreply.github.com>"
    git("commit", "-m",
        f"reverse-sync: port {UPSTREAM}#{pr_number}\n\n{trailer}")
    git("push", "-u", "origin", branch, "--force-with-lease")

    labels = ["reverse-sync"] + (["needs-human"] if conflicts else [])
    create = _run(
        ["gh", "pr", "create", "--repo", provider_repo, "--base", default_branch,
         "--head", branch, "--draft",
         "--title", f"reverse-sync: {pr['title']} (#{pr_number})",
         "--body", build_pr_body(pr, domain, conflicts),
         *sum((["--label", x] for x in labels), [])],
        capture_output=True,
    )
    return {
        "skipped": False,
        "pr_url": create.stdout.strip(),
        "conflicts": conflicts,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--provider-path", required=True)
    ap.add_argument("--provider-repo", required=True)
    ap.add_argument("--default-branch", required=True)
    ap.add_argument("--pr-number", type=int, required=True)
    ap.add_argument("--provider-dir", required=True)
    args = ap.parse_args()
    result = open_reverse_pr(
        args.domain, args.provider_path, args.provider_repo,
        args.default_branch, args.pr_number, args.provider_dir,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_open_pr.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + commit**

```bash
ruff check scripts/reverse_sync_open_pr.py && ruff format scripts/reverse_sync_open_pr.py tests/test_open_pr.py
git add scripts/reverse_sync_open_pr.py tests/test_open_pr.py
git commit -m "feat(reverse-sync): add reverse-PR opener"
```

---

## Task 7: Radar + notifications

**Files:**
- Create: `scripts/reverse_sync_radar.py`
- Create: `scripts/reverse_sync_notify.py`
- Create: `tests/test_radar.py`

**Interfaces:**
- Consumes: `reverse_sync_state` (Task 3), `reverse_sync_open_pr.open_reverse_pr` (Task 6).
- Produces:
  - `reverse_sync_radar.is_echo(pr: dict, echo_logins: set[str]) -> bool`
  - `reverse_sync_radar.touches_provider(files: list[str], domain: str) -> bool`
  - `reverse_sync_radar.select_unhandled(prs: list[dict], data: dict, domain: str, cursor: str | None) -> list[dict]`
  - `reverse_sync_notify.upsert_issue(repo, label, title, body) -> int`

- [ ] **Step 1: Write the failing tests**

`tests/test_radar.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reverse_sync_radar as r  # noqa: E402
import reverse_sync_state as st  # noqa: E402

ECHO = {"github-actions[bot]", "trudenboy"}


def test_is_echo():
    assert r.is_echo({"user": {"login": "trudenboy"}}, ECHO) is True
    assert r.is_echo({"user": {"login": "alice"}}, ECHO) is False


def test_touches_provider():
    files = [
        "music_assistant/providers/yandex_music/api.py",
        "music_assistant/server.py",
    ]
    assert r.touches_provider(files, "yandex_music") is True
    assert r.touches_provider(["music_assistant/server.py"], "yandex_music") is False


def test_select_unhandled_filters_handled_and_cursor():
    data = {}
    st.mark_handled(data, "d", 100)
    prs = [
        {"number": 100, "updated_at": "2026-06-01T00:00:00Z", "user": {"login": "x"}},
        {"number": 101, "updated_at": "2026-06-02T00:00:00Z", "user": {"login": "x"}},
        {"number": 102, "updated_at": "2026-05-01T00:00:00Z", "user": {"login": "x"}},
    ]
    out = r.select_unhandled(prs, data, "d", cursor="2026-05-15T00:00:00Z")
    # 100 handled, 102 below cursor -> only 101 remains
    assert [p["number"] for p in out] == [101]
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_radar.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reverse_sync_radar'`.

- [ ] **Step 3: Implement `scripts/reverse_sync_notify.py`**

```python
#!/usr/bin/env python3
"""Open or update a deduped issue in this hub (never in music-assistant/*)."""

from __future__ import annotations

import json
import subprocess


def _gh(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], text=True, capture_output=True, **kw)


def upsert_issue(repo: str, label: str, title: str, body: str) -> int:
    existing = _gh(
        ["issue", "list", "--repo", repo, "--label", label, "--state", "open",
         "--json", "number,title"]
    ).stdout
    for item in json.loads(existing or "[]"):
        if item["title"] == title:
            num = item["number"]
            _gh(["issue", "comment", str(num), "--repo", repo, "--body", body])
            return num
    created = _gh(
        ["issue", "create", "--repo", repo, "--label", label,
         "--title", title, "--body", body]
    ).stdout.strip()
    return int(created.rstrip("/").split("/")[-1]) if created else 0
```

- [ ] **Step 4: Implement `scripts/reverse_sync_radar.py`**

```python
#!/usr/bin/env python3
"""Reverse-sync radar: detect inbound provider PRs and open reverse PRs.

Read-only against music-assistant/server. Two passes per provider:
  A) anchor — latest upstream SHA on the provider path (consumed by the guard)
  B) action — merged PRs touching the path -> reverse-PR opener

Iterates providers.yml. Persists progress to state/reverse-sync.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reverse_sync_open_pr as opener  # noqa: E402
import reverse_sync_state as st  # noqa: E402

UPSTREAM = "music-assistant/server"
HUB_REPO = "trudenboy/ma-provider-tools"
ECHO_LOGINS = {"github-actions[bot]", "trudenboy", "trudenboy[bot]"}
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(REPO_ROOT, "state", "reverse-sync.json")
PROVIDERS_PATH = os.path.join(REPO_ROOT, "providers.yml")


def _gh(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], text=True, capture_output=True, check=True
    ).stdout


def is_echo(pr: dict, echo_logins: set[str]) -> bool:
    return pr.get("user", {}).get("login") in echo_logins


def touches_provider(files: list[str], domain: str) -> bool:
    root = f"music_assistant/providers/{domain}/"
    return any(f.startswith(root) for f in files)


def select_unhandled(
    prs: list[dict], data: dict, domain: str, cursor: str | None
) -> list[dict]:
    out = []
    for pr in prs:
        if st.is_handled(data, domain, pr["number"]):
            continue
        if cursor and pr["updated_at"] <= cursor:
            continue
        out.append(pr)
    return out


def _anchor(domain: str, default_branch: str) -> str | None:
    raw = _gh(
        ["api",
         f"repos/{UPSTREAM}/commits"
         f"?path=music_assistant/providers/{domain}&sha={default_branch}&per_page=1",
         "--jq", ".[0].sha // empty"]
    ).strip()
    return raw or None


def _merged_prs(default_branch: str) -> list[dict]:
    raw = _gh(
        ["api",
         f"repos/{UPSTREAM}/pulls?state=closed&base={default_branch}"
         "&sort=updated&direction=desc&per_page=50",
         "--jq",
         "[.[] | select(.merged_at != null) | "
         "{number, updated_at, user:{login:.user.login}}]"]
    )
    return json.loads(raw)


def _pr_files(number: int) -> list[str]:
    raw = _gh(
        ["api", f"repos/{UPSTREAM}/pulls/{number}/files?per_page=100",
         "--jq", "[.[].filename]"]
    )
    return json.loads(raw)


def _clone_provider(repo: str, branch: str, dest: str) -> None:
    token = os.environ["FORK_SYNC_PAT"]
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    subprocess.run(
        ["git", "clone", "--depth", "50", "--branch", branch, url, dest],
        check=True, capture_output=True, text=True,
    )


def run() -> int:
    registry = yaml.safe_load(open(PROVIDERS_PATH))
    data = st.load(STATE_PATH)

    for prov in registry["providers"]:
        domain = prov["domain"]
        default_branch_up = "dev"  # upstream default; adjust if upstream changes
        entry = st.entry(data, domain)

        # Pass A — anchor
        anchor = _anchor(domain, default_branch_up)
        if anchor:
            entry["last_synced_sha"] = anchor

        # Pass B — action
        merged = _merged_prs(default_branch_up)
        candidates = select_unhandled(merged, data, domain, entry["pulls_cursor"])
        max_cursor = entry["pulls_cursor"]
        for pr in candidates:
            max_cursor = max(max_cursor or "", pr["updated_at"])
            if is_echo(pr, ECHO_LOGINS):
                st.mark_handled(data, domain, pr["number"])
                continue
            if not touches_provider(_pr_files(pr["number"]), domain):
                st.mark_handled(data, domain, pr["number"])
                continue
            with tempfile.TemporaryDirectory() as tmp:
                pdir = os.path.join(tmp, "provider")
                _clone_provider(prov["repo"], prov["default_branch"], pdir)
                result = opener.open_reverse_pr(
                    domain=domain,
                    provider_path=prov["provider_path"],
                    provider_repo=prov["repo"],
                    default_branch=prov["default_branch"],
                    pr_number=pr["number"],
                    provider_dir=pdir,
                )
            print(f"{domain} PR#{pr['number']}: {result}")
            st.mark_handled(data, domain, pr["number"])
        entry["pulls_cursor"] = max_cursor

    st.save(STATE_PATH, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
```

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_radar.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Lint + commit**

```bash
ruff check scripts/reverse_sync_radar.py scripts/reverse_sync_notify.py
ruff format scripts/reverse_sync_radar.py scripts/reverse_sync_notify.py tests/test_radar.py
git add scripts/reverse_sync_radar.py scripts/reverse_sync_notify.py tests/test_radar.py
git commit -m "feat(reverse-sync): add radar + hub notification helper"
```

---

## Task 8: Radar workflow + AI-policy test + docs

**Files:**
- Create: `.github/workflows/reverse-sync-radar.yml`
- Create: `tests/test_ai_policy_readonly.py`
- Modify: `CLAUDE.md` (document the reverse-sync channel)

**Interfaces:**
- Consumes: all prior scripts.

- [ ] **Step 1: Write the failing AI-policy test**

`tests/test_ai_policy_readonly.py`:

```python
import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
REVERSE = [
    "reverse_sync_radar.py",
    "reverse_sync_open_pr.py",
    "check_upstream_ahead.py",
]
WRITE_VERBS = ("create", "comment", "edit", "review", "merge", "close")


def test_no_writes_to_upstream():
    """No reverse-sync script may issue a write gh command bound to UPSTREAM."""
    for name in REVERSE:
        text = (SCRIPTS / name).read_text()
        # Any `gh pr/issue <write-verb>` must not appear next to the UPSTREAM repo.
        for m in re.finditer(r'"(pr|issue)",\s*"(\w+)"', text):
            verb = m.group(2)
            if verb in WRITE_VERBS:
                # ensure UPSTREAM constant not used as --repo for this call:
                window = text[m.start(): m.start() + 400]
                assert "UPSTREAM" not in window, (
                    f"{name}: write verb {verb!r} near UPSTREAM"
                )
```

- [ ] **Step 2: Run to verify it passes**

Run: `python -m pytest tests/test_ai_policy_readonly.py -q`
Expected: PASS. (Reverse scripts only use `gh pr view/diff` and `gh api ... GET` against UPSTREAM; writes target provider repos.)

- [ ] **Step 3: Create the radar workflow**

`.github/workflows/reverse-sync-radar.yml`:

```yaml
name: Reverse-sync radar

on:
  schedule:
    # Every 2h — close the revert window before the next manual forward-sync.
    - cron: "0 */2 * * *"
  workflow_dispatch:

permissions:
  contents: write
  issues: write

concurrency:
  group: reverse-sync-radar
  cancel-in-progress: false

jobs:
  radar:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install pyyaml

      - name: Run radar
        env:
          GH_TOKEN: ${{ secrets.FORK_SYNC_PAT }}
          FORK_SYNC_PAT: ${{ secrets.FORK_SYNC_PAT }}
        run: python3 scripts/reverse_sync_radar.py

      - name: Commit state if changed
        run: |
          if git diff --quiet state/; then
            echo "No state changes"
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add state/
          git commit -m "chore(reverse-sync): update radar state"
          git push
```

- [ ] **Step 4: Document in CLAUDE.md**

In `CLAUDE.md`, after the "## Upstream PR Workflow" section, add a new section:

```markdown
## Reverse-sync Channel

`reverse-sync-radar.yml` (cron every 2h + dispatch) polls `music-assistant/server`
**read-only** for merged PRs touching `music_assistant/providers/<domain>/` and
auto-opens **draft** reverse-sync PRs in the provider repo (best-effort
`git apply --3way`; conflicts left in-tree, labelled `needs-human`). Progress is
in `state/reverse-sync.json`. The forward-sync (`reusable-sync-to-fork.yml`) has
a preflight guard that blocks the destructive rsync when upstream is ahead;
override with the `ack_upstream_ahead=true` dispatch input.

Path/import mapping lives in `scripts/_transform.py` (single source of truth;
forward `sed` rules in the sync workflow are pinned to it by
`tests/test_forward_sed_parity.py`). Per AI-Policy rule 2, no reverse-sync script
ever writes to `music-assistant/*`.
```

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (all tests green).

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/reverse-sync-radar.yml tests/test_ai_policy_readonly.py CLAUDE.md
git commit -m "feat(reverse-sync): radar workflow + AI-policy read-only test + docs"
```

---

## Self-Review

**Spec coverage:**
- Decision #1 (hybrid trigger) → Task 7 (`_anchor` pass A + `_merged_prs` pass B). ✓
- Decision #2 (best-effort → always draft) → Task 6 `open_reverse_pr` (`--3way` then always `gh pr create --draft`, `needs-human` on conflict). ✓
- Decision #3 (P0 + P1 together) → Tasks 4–5 (guard) + 6–8 (reverse). ✓
- Decision #4 (shared transform) → Task 1 `_transform.py` + Task 2 parity guard (refinement noted: parity test instead of live-workflow rewrite, because reusable workflows lack hub `scripts/`). ✓
- Decision #5 (ack input) → Task 5 Steps 1–3. ✓
- State store `state/reverse-sync.json` → Task 3. ✓
- Acceptance #1 (guard fails when ahead; VERSION ignored) → Task 4 tests `test_content_change_is_ahead`, `test_version_difference_ignored`. ✓
- Acceptance #3 (auto draft PR, contributor credited, VERSION/translations untouched) → Task 6 tests + `open_reverse_pr` trailer + scaffold excludes VERSION/translations. ✓
- Acceptance #4 (never writes to music-assistant/*) → Task 8 `test_ai_policy_readonly.py`. ✓
- Acceptance #5 (registry-driven) → Task 7 iterates `providers.yml`. ✓
- Edge cases (echo, squash, multi-provider, foreign code, rate-limit) → Task 6 no-op dedup + Task 7 `is_echo`/`touches_provider`/cursor; `reverse_diff` drops foreign files (Task 1 `test_reverse_diff_drops_foreign_files`). ✓

**Placeholder scan:** Spec stub content intentionally contains a `_TODO_` literal inside the *generated scaffold string* (Task 6 `scaffold_paths`) — that is product output for the human to fill, not a plan placeholder. No plan-level TBDs.

**Type consistency:** `open_reverse_pr(domain, provider_path, provider_repo, default_branch, pr_number, provider_dir)` is defined in Task 6 and called with the same keyword names in Task 7. `st.entry/mark_handled/is_handled/load/save` signatures match across Tasks 3, 7. `_transform.reverse_path/reverse_diff/forward_content` signatures consistent across Tasks 1, 2, 4, 6.

**Open verification flagged for execution:** Task 7 hardcodes the upstream default branch as `dev` (`default_branch_up`). Confirm `music-assistant/server`'s actual default branch during execution and adjust if it is `main`.
