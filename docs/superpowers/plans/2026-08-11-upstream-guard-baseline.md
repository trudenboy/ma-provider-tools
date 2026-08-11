# Upstream Guard Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow FastMCP forward sync to acknowledge the exact reviewed upstream tree while continuing to block every upstream source or test blob changed after it.

**Architecture:** Store one optional immutable upstream SHA in the provider registry, render it into both pipeline sync calls, and pass it through the reusable workflow to the guard. The guard compares current upstream blob IDs with the baseline tree only after its existing automatic proofs, and fails closed whenever the baseline cannot prove an exact unchanged blob.

**Tech Stack:** Python 3.12+, pytest, PyYAML, JSON Schema 2020-12, Jinja2 with `StrictUndefined`, Bash, GitHub Actions reusable workflows.

## Global Constraints

- The FastMCP baseline is exactly `a91504084610a817212c17174662cf73a4829bd9`.
- `music-assistant/*` remains read-only; only Git tree reads are allowed.
- A missing, malformed, inaccessible, absent, added, or changed baseline path must remain blocking.
- Direct reusable-workflow callers cannot bypass immutability: the guard CLI rejects every baseline except a full 40-character lowercase SHA before upstream lookup.
- Providers without `upstream_guard_baseline` retain byte-for-byte equivalent workflow behavior.
- Do not use `ack_upstream_ahead=true` for this rollout.
- Follow strict RED-GREEN-REFACTOR: every production behavior change begins with a test observed failing for the intended reason.

---

## File Map

| File | Responsibility |
| --- | --- |
| `providers.yml` | Select the exact acknowledged upstream tree for FastMCP. |
| `schemas/providers.schema.json` | Restrict configured baselines to full lowercase Git SHAs. |
| `scripts/render_for_provider.py` | Supply the optional registry value to local/config-sync rendering. |
| `scripts/distribute.py` | Supply the optional registry value to fleet wrapper distribution. |
| `scripts/validate_templates.py` | Supply a default value during strict template validation. |
| `wrappers/pipeline.yml.j2` | Pass the configured baseline into both generated sync jobs. |
| `scripts/check_upstream_ahead.py` | Prove residual upstream files are unchanged from the acknowledged tree. |
| `.github/workflows/reusable-sync-to-fork.yml` | Safely pass the optional workflow input to the Python guard. |
| `tests/test_render_for_provider.py` | Exercise the real wrapper renderer and verify provider-specific output. |
| `tests/test_provider_registry.py` | Verify valid and invalid baseline registry values against the real schema. |
| `tests/test_check_upstream_ahead.py` | Verify exact-blob and fail-closed guard semantics. |
| `tests/test_sync_workflow.py` | Execute the extracted preflight shell with a fake external Python boundary and inspect guard arguments. |

---

### Task 1: Registry Contract and Generated Pipeline

**Files:**
- Modify: `providers.yml`
- Modify: `schemas/providers.schema.json`
- Modify: `scripts/render_for_provider.py`
- Modify: `scripts/distribute.py`
- Modify: `scripts/validate_templates.py`
- Modify: `wrappers/pipeline.yml.j2`
- Modify: `tests/test_render_for_provider.py`
- Create: `tests/test_provider_registry.py`

**Interfaces:**
- Consumes: optional provider mapping key `upstream_guard_baseline`.
- Produces: template context value `upstream_guard_baseline: str`, defaulting to `""`; generated reusable-workflow input of the same name in both sync jobs when non-empty.

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_provider_registry.py` with literal accepted and rejected values:

```python
import copy
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "a91504084610a817212c17174662cf73a4829bd9"


def _fastmcp() -> dict:
    registry = yaml.safe_load((ROOT / "providers.yml").read_text())
    return copy.deepcopy(
        next(p for p in registry["providers"] if p["domain"] == "fastmcp_server")
    )


def _errors(provider: dict) -> list:
    schema = json.loads((ROOT / "schemas/providers.schema.json").read_text())
    return list(Draft202012Validator(schema["$defs"]["provider"]).iter_errors(provider))


def test_full_lowercase_upstream_guard_baseline_is_valid() -> None:
    provider = _fastmcp()
    provider["upstream_guard_baseline"] = BASELINE
    assert _errors(provider) == []


def test_nonimmutable_upstream_guard_baselines_are_rejected() -> None:
    for invalid in ("main", "a915040", BASELINE.upper()):
        provider = _fastmcp()
        provider["upstream_guard_baseline"] = invalid
        assert _errors(provider), invalid
```

The mutation caught is accepting a branch, short hash, or uppercase noncanonical value where the workflow requires an immutable canonical SHA.

- [ ] **Step 2: Run schema tests and verify RED**

Run:

```bash
uv run --no-project --with 'pytest>=8,<9' --with 'pyyaml>=6' --with 'jsonschema>=4' pytest tests/test_provider_registry.py -q
```

Expected: the valid-value test fails because the schema rejects the unknown property.

- [ ] **Step 3: Add the schema property and FastMCP value**

Add this provider property in `schemas/providers.schema.json`:

```json
"upstream_guard_baseline": {
  "type": "string",
  "pattern": "^[0-9a-f]{40}$",
  "description": "Immutable music-assistant/server commit whose unchanged provider blobs are acknowledged by the forward-sync guard."
}
```

Add this key to the `fastmcp_server` entry in `providers.yml`:

```yaml
    upstream_guard_baseline: a91504084610a817212c17174662cf73a4829bd9
```

- [ ] **Step 4: Run schema tests and verify GREEN**

Run the Step 2 command. Expected: `2 passed`.

- [ ] **Step 5: Write failing renderer tests**

Extend `tests/test_render_for_provider.py` with a helper that invokes the real `render_for_provider.py` entry point and parses its output:

```python
BASELINE = "a91504084610a817212c17174662cf73a4829bd9"


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
```

Also add a test of the fleet distribution entry point so a missing
`scripts/distribute.py` context key cannot escape the local renderer test:

```python
def test_distributor_renders_fastmcp_pipeline_with_baseline() -> None:
    from scripts.distribute import render_wrappers

    registry = yaml.safe_load((REPO_ROOT / "providers.yml").read_text())
    provider = next(
        p for p in registry["providers"] if p["domain"] == "fastmcp_server"
    )
    rendered = render_wrappers(provider, registry["providers"])
    jobs = yaml.safe_load(rendered[".github/workflows/pipeline.yml"])["jobs"]
    assert jobs["sync-integration"]["with"]["upstream_guard_baseline"] == BASELINE
```

The mutations caught are omitting either sync job, leaking the value to all providers, or updating only one of the two renderer contexts.

- [ ] **Step 6: Run renderer tests and verify RED**

Run:

```bash
uv run --no-project --with 'pytest>=8,<9' --with 'pyyaml>=6' --with 'jinja2>=3' pytest tests/test_render_for_provider.py -q
```

Expected: FastMCP output lacks `upstream_guard_baseline`.

- [ ] **Step 7: Implement minimal template propagation**

Add this key to the context dictionaries in `scripts/render_for_provider.py`, `scripts/distribute.py`, and `scripts/validate_templates.py`:

```python
"upstream_guard_baseline": provider.get("upstream_guard_baseline", ""),
```

Use `base.get(...)` instead of `provider.get(...)` in `validate_templates.py`.

In each sync job's `with:` mapping in `wrappers/pipeline.yml.j2`, add the conditional input immediately after `provider_path`:

```jinja2
{%- if upstream_guard_baseline %}
      upstream_guard_baseline: {{ upstream_guard_baseline }}
{%- endif %}
```

- [ ] **Step 8: Run renderer and validation tests and verify GREEN**

Run:

```bash
uv run --no-project --with 'pytest>=8,<9' --with 'pyyaml>=6' --with 'jinja2>=3' pytest tests/test_render_for_provider.py -q
uv run --no-project --with 'pyyaml>=6' --with 'jinja2>=3' python scripts/validate_templates.py
uv run --no-project --with 'pyyaml>=6' --with 'jsonschema>=4' python scripts/validate_providers_yml.py
```

Expected: all commands succeed; ordinary-provider rendering contains no blank placeholder input.

- [ ] **Step 9: Commit the registry and rendering contract**

```bash
git add providers.yml schemas/providers.schema.json scripts/render_for_provider.py scripts/distribute.py scripts/validate_templates.py wrappers/pipeline.yml.j2 tests/test_render_for_provider.py tests/test_provider_registry.py
git commit -m "feat: configure immutable upstream guard baseline"
```

---

### Task 2: Exact-Blob Baseline Filter

**Files:**
- Modify: `scripts/check_upstream_ahead.py`
- Modify: `tests/test_check_upstream_ahead.py`

**Interfaces:**
- Consumes: residual provider-relative paths, current upstream tree map, provider domain/path, and optional acknowledged ref.
- Produces: `drop_acknowledged_baseline(...) -> list[str]`, preserving a sorted residual list and never dropping on lookup failure.
- CLI: optional `--acknowledged-upstream-ref REF`, validated as a full 40-character lowercase commit SHA before upstream lookup.

- [ ] **Step 1: Write failing exact-blob tests**

Append to `tests/test_check_upstream_ahead.py`:

```python
ACK_REF = "a91504084610a817212c17174662cf73a4829bd9"


def _acknowledged(
    ahead: list[str], current: dict[str, str], baseline: dict[str, str]
) -> list[str]:
    return g.drop_acknowledged_baseline(
        ahead,
        current,
        DOMAIN,
        PP,
        ACK_REF,
        lambda _domain, _ref: baseline,
    )


def test_baseline_drops_only_unchanged_current_blob() -> None:
    current = {ROOT + "legacy.py": "same", ROOT + "changed.py": "new"}
    baseline = {ROOT + "legacy.py": "same", ROOT + "changed.py": "old"}
    assert _acknowledged(
        ["provider/legacy.py", "provider/changed.py"], current, baseline
    ) == ["provider/changed.py"]


def test_baseline_keeps_current_path_absent_from_baseline() -> None:
    current = {ROOT + "new.py": "new"}
    assert _acknowledged(["provider/new.py"], current, {}) == ["provider/new.py"]


def test_baseline_handles_source_and_test_paths() -> None:
    test_path = f"tests/providers/{DOMAIN}/test_legacy.py"
    current = {ROOT + "legacy.py": "src", test_path: "test"}
    assert _acknowledged(
        ["provider/legacy.py", "tests/test_legacy.py"], current, current
    ) == []


def test_baseline_lookup_failure_stays_fail_closed() -> None:
    current = {ROOT + "legacy.py": "same"}

    def fail(_domain: str, _ref: str) -> dict[str, str]:
        raise RuntimeError("unavailable")

    assert g.drop_acknowledged_baseline(
        ["provider/legacy.py"], current, DOMAIN, PP, ACK_REF, fail
    ) == ["provider/legacy.py"]
```

The mutations caught are comparing paths only, ignoring test roots, allowing files absent at baseline, or swallowing lookup errors as success.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run --no-project --with 'pytest>=8,<9' --with 'pyyaml>=6' pytest tests/test_check_upstream_ahead.py -q
```

Expected: collection or execution fails because `drop_acknowledged_baseline` does not exist.

- [ ] **Step 3: Implement the minimal filter**

Add a tree-listing callable alias and the function to `scripts/check_upstream_ahead.py`:

```python
UpstreamTreeLister = Callable[[str, str], dict[str, str]]


def drop_acknowledged_baseline(
    ahead: list[str],
    upstream_files: dict[str, str],
    domain: str,
    provider_path: str,
    acknowledged_ref: str,
    list_upstream_tree: UpstreamTreeLister,
) -> list[str]:
    """Drop residual paths unchanged since an explicitly reviewed tree."""
    if not ahead or not acknowledged_ref:
        return sorted(ahead)
    try:
        baseline = list_upstream_tree(domain, acknowledged_ref)
    except Exception as exc:  # noqa: BLE001 -- fail-closed guard boundary
        print(
            f"::warning::could not resolve acknowledged upstream baseline "
            f"{acknowledged_ref} ({exc}); keeping all differences flagged.",
            file=sys.stderr,
        )
        return sorted(ahead)

    remaining: list[str] = []
    for rel in sorted(ahead):
        up_path = t.forward_path(rel, domain, provider_path)
        if (
            up_path is None
            or up_path not in baseline
            or upstream_files.get(up_path) != baseline[up_path]
        ):
            remaining.append(rel)
            continue
        print(
            f"::notice::{rel}: current upstream blob matches acknowledged "
            f"baseline {acknowledged_ref} (reviewed divergence — not blocking).",
            file=sys.stderr,
        )
    return remaining
```

The existing canonical mapper is `_transform.forward_path(rel_path, domain, provider_path)`; use it directly and do not introduce a second path map.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the Step 2 command. Expected: all `test_check_upstream_ahead.py` tests pass.

- [ ] **Step 5: Write a failing CLI integration test**

Add a test that patches only the external tree/fetch/transform boundaries, invokes `main()` with `--acknowledged-upstream-ref`, and asserts an unchanged architectural difference exits zero:

```python
import pytest


def test_main_applies_acknowledged_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    current = {ROOT + "legacy.py": "same"}
    refs: list[str] = []

    def list_tree(_domain: str, ref: str) -> dict[str, str]:
        refs.append(ref)
        return current

    monkeypatch.setattr(g, "_list_upstream_tree", list_tree)
    monkeypatch.setattr(g, "transformed_hashes", lambda *_args: {})
    monkeypatch.setattr(g, "drop_provider_ahead", lambda ahead, *_args: ahead)
    monkeypatch.setattr(g, "drop_already_ported", lambda ahead, *_args: ahead)
    monkeypatch.setattr(g, "_fetch_upstream_pyproject", lambda _ref: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_upstream_ahead.py",
            "--domain",
            DOMAIN,
            "--provider-path",
            PP,
            "--provider-dir",
            ".",
            "--acknowledged-upstream-ref",
            ACK_REF,
        ],
    )

    assert g.main() == 0
    assert refs == ["HEAD", ACK_REF]
```

Place the new `pytest` import with the existing imports. Do not assert calls on mocks. The observable contract is exit code plus refs consumed.

- [ ] **Step 6: Run the CLI test and verify RED**

Run:

```bash
uv run --no-project --with 'pytest>=8,<9' --with 'pyyaml>=6' pytest tests/test_check_upstream_ahead.py::test_main_applies_acknowledged_baseline -q
```

Expected: argparse rejects the unknown option.

- [ ] **Step 7: Wire the CLI after existing automatic proofs**

Add a parser type that rejects mutable or noncanonical refs before the first
upstream tree lookup:

```python
def _immutable_commit_sha(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value):
        return value
    raise argparse.ArgumentTypeError(
        "acknowledged upstream ref must be a full 40-character lowercase commit SHA"
    )
```

Add the argument with that type:

```python
ap.add_argument(
    "--acknowledged-upstream-ref",
    default="",
    type=_immutable_commit_sha,
    help="immutable upstream commit whose unchanged residual blobs are reviewed",
)
```

After `drop_already_ported(...)` and before the final `if ahead:` block, add:

```python
if ahead and args.acknowledged_upstream_ref:
    ahead = drop_acknowledged_baseline(
        ahead,
        upstream,
        args.domain,
        args.provider_path,
        args.acknowledged_upstream_ref,
        _list_upstream_tree,
    )
```

- [ ] **Step 8: Run all guard tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass with the baseline filter executing last.

- [ ] **Step 9: Commit the guard behavior**

```bash
git add scripts/check_upstream_ahead.py tests/test_check_upstream_ahead.py
git commit -m "fix: acknowledge unchanged reviewed upstream blobs"
```

---

### Task 3: Reusable Workflow Argument Propagation

**Files:**
- Modify: `.github/workflows/reusable-sync-to-fork.yml`
- Create: `tests/test_sync_workflow.py`

**Interfaces:**
- Consumes: workflow-call string input `upstream_guard_baseline`, default `""`.
- Produces: `--acknowledged-upstream-ref "$UPSTREAM_GUARD_BASELINE"` as two shell arguments only when non-empty.

- [ ] **Step 1: Write a failing executable shell-contract test**

Create `tests/test_sync_workflow.py`. Parse the real YAML workflow, extract the preflight script, replace only the GitHub manifest/provider expressions with literals, and execute it with a fake `python3` executable. The fake prints `fastmcp_server` for the manifest probe and records the guard invocation as NUL-delimited arguments for unambiguous quoting checks:

```python
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "a91504084610a817212c17174662cf73a4829bd9"


def _preflight_script() -> str:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-sync-to-fork.yml").read_text()
    )
    steps = workflow["jobs"]["sync"]["steps"]
    script = next(
        step["run"]
        for step in steps
        if step.get("name") == "Preflight — block if upstream is ahead"
    )
    return script.replace("${{ inputs.manifest_path }}", "provider/manifest.json").replace(
        "${{ inputs.provider_path }}", "provider/"
    )


def _run_preflight(tmp_path: Path, baseline: str) -> list[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ $1 == -c ]]; then printf fastmcp_server; exit 0; fi\n"
        "printf '%s\\0' \"$@\" > \"$CAPTURE\"\n"
    )
    fake_python.chmod(0o755)
    capture = tmp_path / "args"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _preflight_script()],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "CAPTURE": str(capture),
            "UPSTREAM_GUARD_BASELINE": baseline,
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return capture.read_bytes().decode().rstrip("\0").split("\0")


def test_preflight_passes_configured_baseline_as_one_argument(tmp_path: Path) -> None:
    args = _run_preflight(tmp_path, BASELINE)
    assert args[-2:] == ["--acknowledged-upstream-ref", BASELINE]


def test_preflight_omits_empty_baseline(tmp_path: Path) -> None:
    args = _run_preflight(tmp_path, "")
    assert "--acknowledged-upstream-ref" not in args


def test_workflow_declares_and_maps_upstream_guard_baseline() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-sync-to-fork.yml").read_text()
    )
    trigger = workflow.get("on", workflow.get(True))
    declared = trigger["workflow_call"]["inputs"]["upstream_guard_baseline"]
    assert declared["type"] == "string"
    assert declared["default"] == ""

    steps = workflow["jobs"]["sync"]["steps"]
    preflight = next(
        step
        for step in steps
        if step.get("name") == "Preflight — block if upstream is ahead"
    )
    assert preflight["env"]["UPSTREAM_GUARD_BASELINE"] == (
        "${{ inputs.upstream_guard_baseline }}"
    )
```

The mutations caught are unconditional empty arguments, incorrect option names, lost values, or shell word splitting.

- [ ] **Step 2: Run the workflow tests and verify RED**

Run:

```bash
uv run --no-project --with 'pytest>=8,<9' --with 'pyyaml>=6' pytest tests/test_sync_workflow.py -q
```

Expected: configured baseline is absent from captured arguments.

- [ ] **Step 3: Add the reusable-workflow input and safe Bash array**

Declare under `workflow_call.inputs`:

```yaml
      upstream_guard_baseline:
        description: "Immutable upstream commit whose unchanged provider blobs are acknowledged"
        type: string
        default: ""
```

Add this environment value to the preflight step:

```yaml
          UPSTREAM_GUARD_BASELINE: ${{ inputs.upstream_guard_baseline }}
```

Before the guard invocation, build a quoted array:

```bash
          BASELINE_ARGS=()
          if [[ -n "$UPSTREAM_GUARD_BASELINE" ]]; then
            BASELINE_ARGS+=(--acknowledged-upstream-ref "$UPSTREAM_GUARD_BASELINE")
          fi
```

Append `"${BASELINE_ARGS[@]}"` to the Python command after `--provider-dir provider-repo`.

- [ ] **Step 4: Run workflow tests and verify GREEN**

Run the Step 2 command. Expected: `2 passed`.

- [ ] **Step 5: Commit reusable workflow propagation**

```bash
git add .github/workflows/reusable-sync-to-fork.yml tests/test_sync_workflow.py
git commit -m "fix: pass upstream guard baseline through sync workflow"
```

---

### Task 4: Full Verification and Review Handoff

**Files:**
- Verify all files changed in Tasks 1-3.
- Modify only files required to correct failures caused by this branch.

**Interfaces:**
- Produces: a reviewable tools PR; no merge occurs without explicit human approval.

- [ ] **Step 1: Run focused behavior and renderer tests**

```bash
uv run --no-project --with 'pytest>=8,<9' --with 'pyyaml>=6' --with 'jinja2>=3' --with 'jsonschema>=4' pytest tests/test_check_upstream_ahead.py tests/test_render_for_provider.py tests/test_provider_registry.py tests/test_sync_workflow.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run canonical validators**

```bash
uv run --no-project --with 'pyyaml>=6' --with 'jinja2>=3' python scripts/validate_templates.py
uv run --no-project --with 'pyyaml>=6' --with 'jsonschema>=4' python scripts/validate_providers_yml.py
```

Expected: every template and every provider registry entry validates.

- [ ] **Step 3: Run the full suite from a fresh command**

```bash
uv run --no-project --with 'pytest>=8,<9' --with 'pyyaml>=6' --with 'jinja2>=3' --with 'jsonschema>=4' pytest tests/ -q
```

Expected: all tests pass with no collection errors.

- [ ] **Step 4: Run repository hygiene checks**

```bash
git diff --check origin/main...HEAD
uv run --no-project --with pre-commit --with 'pyyaml>=6' --with 'jinja2>=3' --with 'jsonschema>=4' pre-commit run --all-files --show-diff-on-failure
git status --short
```

Expected: no whitespace errors, pre-commit succeeds, and only intentional branch changes exist.

- [ ] **Step 5: Inspect the final diff and commits**

```bash
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- providers.yml schemas/providers.schema.json wrappers/pipeline.yml.j2 .github/workflows/reusable-sync-to-fork.yml scripts/check_upstream_ahead.py
git log --oneline origin/main..HEAD
```

Confirm the diff contains no upstream writes, no global bypass, no generated provider files, and no unrelated refactor.

- [ ] **Step 6: Push and open a draft tools PR**

Create the untracked file `/tmp/ma-provider-tools-upstream-guard-pr.md` with this exact reviewed body using `apply_patch`:

```markdown
## Summary

- add an immutable per-provider upstream guard baseline
- acknowledge only blobs unchanged since that exact tree
- keep new, changed, absent, or unresolvable upstream paths fail-closed

## Root cause

FastMCP has reviewed architectural ports that cannot be proven by the existing
release-tag or line-reflection passes. The guard therefore blocks 19 legacy
paths even though upstream has not changed them after the reviewed tree.

## Verification

- focused baseline, registry, renderer, and workflow tests
- full pytest suite
- template and provider-schema validators
- pre-commit

## Rollout

After merge, distribute the generated FastMCP pipeline wrapper and run a fresh
provider Pipeline. No `ack_upstream_ahead` override is enabled.
```

Then run:

```bash
git push -u origin fix/upstream-guard-baseline
gh pr create --draft --base main --head fix/upstream-guard-baseline --title "fix: acknowledge immutable upstream guard baseline" --body-file /tmp/ma-provider-tools-upstream-guard-pr.md
```

Do not post replies to human comments and do not merge the PR.

- [ ] **Step 7: Pause for human review and merge approval**

Report the PR URL, check results, exact baseline SHA, and residual risk. Wait for explicit approval before merging the tools PR. After merge, verify the mechanically generated provider wrapper PR, then dispatch a fresh provider Pipeline and confirm both sync jobs succeed.
