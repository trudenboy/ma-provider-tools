# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Does

Central infrastructure for Music Assistant custom providers. It manages two things:
1. **Shared reusable workflows** (`reusable-*.yml`) — logic called by all provider repos via `uses:`
2. **Wrapper file distribution** — Jinja2 templates rendered per-provider and pushed as PRs

Changes to `reusable-*.yml` take effect immediately in all provider repos (no PRs needed).
Changes to `wrappers/*.j2` or `providers.yml` trigger `distribute.yml`, which auto-creates PRs in every provider repo.

## Key Files

| File | Role |
|------|------|
| `providers.yml` | Registry of all providers — single source of truth |
| `scripts/distribute.py` | Renders Jinja2 templates and creates PRs in provider repos |
| `wrappers/*.j2` | Templates rendered once per provider; use `{% raw %}...{% endraw %}` around GitHub Actions expression syntax (`${{ }}`) to prevent Jinja2 from interpreting it |
| `.github/workflows/reusable-*.yml` | Shared logic called by provider repos via `workflow_call` |
| `wrappers/scripts/check_method_order.py.j2` | Vendored mirror of upstream's method-order rule (private methods last), distributed into each provider's pre-commit gate and pinned by `check_config_sync.py` (issue #115) |
| `.github/workflows/distribute.yml` | Runs `distribute.py` on push to `main` when wrappers or registry changes |
| `scripts/reverse_sync_*.py`, `scripts/check_upstream_ahead.py`, `scripts/_transform.py` | Reverse-sync channel (see "Reverse-sync Channel" below) |
| `state/reverse-sync.json` | Committed radar progress state (per-domain `handled_prs` / cursor / anchor) |

## Running distribute.py Locally

```bash
pip install jinja2 pyyaml
GH_TOKEN=<your-pat> python3 scripts/distribute.py

# Dry run (no PRs created):
GH_TOKEN=<your-pat> python3 scripts/distribute.py --dry-run
```

Requires `gh` CLI and a PAT with `contents:write` on all provider repos.

## providers.yml Schema

```yaml
providers:
  - domain: my_provider          # matches manifest.json domain field
    repo: trudenboy/ma-provider-my-provider
    default_branch: dev          # branch distribute.py targets for PRs
    manifest_path: provider/manifest.json
    provider_path: provider/
    provider_type: music_provider  # or player_provider or plugin_provider
    legacy_files:                # optional: files to delete during distribution
      - .github/workflows/old.yml
```

`provider_type` controls CI behavior in `reusable-test.yml`:
- `music_provider` — uses upstream `music-assistant/server` (lighter CI)
- `player_provider` — uses `trudenboy/ma-server` fork for tests; lint always uses upstream `music-assistant/server`
- `plugin_provider` — uses upstream `music-assistant/server` (same CI as music_provider, for PluginProvider-based providers)

## Pipeline Workflow

`pipeline.yml.j2` implements a multi-stage CI/CD pipeline triggered on push to the provider's dev branch:

```
push dev → prepare → lint+test (gate) → release (if version changed) → sync to fork
```

**Stages:**
1. **prepare** — reads version from `VERSION` file, determines channel (PEP 440: `1.2.0` = stable, `1.2.0b1` = beta), checks if version changed vs latest tag
2. **gate** — calls `reusable-test.yml` (lint + test); blocks pipeline on failure
3. **release** — conditional: only runs if version in `VERSION` file differs from latest tag. Creates tag and GitHub Release (prerelease for beta). CHANGELOG is maintained by hand in the provider repos (Changelog Discipline) — there is no automated write-back (issue #112: a direct push can't satisfy the required version-guard check)
4. **sync** — routes based on channel:
   - **beta** → `integration/dev` in `trudenboy/ma-server`
   - **stable** → `integration/dev` + parallel `upstream/[domain]` (e.g. `upstream/yandex_music`)

**Coexistence with other workflows:**
- `test.yml.j2` — remains for PR checks (push to main only)
- `release.yml.j2` — remains as a manual fallback (workflow_dispatch)

## Upstream PR Workflow

`upstream-pr.yml.j2` is a `workflow_dispatch` flow (separate from the dev → release pipeline) that opens or updates a draft PR in `music-assistant/server` for a given provider release. It rsyncs provider source from a `vX.Y.Z` tag into `music_assistant/providers/<domain>/` and writes the PR body via shell string-concat.

**Co-author carry (issue observed on music-assistant/server#4833):** the sync
commit is a single bot commit, so the workflow collects `Co-authored-by`
trailers from the `PREV_TAG...VERSION` compare range, drops AI-agent / bot
trailers (anthropic/cursor/openai/copilot/claude/opencode/aider/devin/`[bot]`/
github-actions — those stay in the provider repo per AI_POLICY), dedupes, and
appends the human ones to the sync commit message (plus a `### Credits` list in
the PR body). GitHub's squash merge then carries the credit into upstream
history. The pipeline is pinned by `tests/test_human_coauthor_carry.py`.

**PR bodies (auto-generated or manually edited) must match upstream's [`PULL_REQUEST_TEMPLATE.md`](https://github.com/music-assistant/.github/blob/main/.github/PULL_REQUEST_TEMPLATE.md).** Upstream's `pr-labels.yaml` parses the ticked `## Types of changes` checkbox(es) to apply labels; the release-notes generator slots by label. A body without that section silently breaks both.

Required top-level skeleton, in order:

1. `# What does this implement/fix?` — narrative (Source link, What's new, Changed files, prose) lives under this heading.
2. `**Related issue (if applicable):**` block.
3. `## Types of changes` — tick **exactly one** box: upstream's `Apply` check now rejects multi-tick bodies ("Tick exactly one", observed 2026-07-16 on PR #4827). Pick the dominant type; the `change_type` workflow input still accepts a comma-separated list but only the first box survives review.
4. `## Checklist` — contributor confirmations. The `I have read and complied with the project's AI Policy` checkbox is the human-attestation checkpoint; no separate attestation block.

When editing a live PR, use `gh api repos/music-assistant/server/pulls/<N> -X PATCH -F body=@file.md`. `gh pr edit` is currently broken on this repo by deprecated Projects-classic GraphQL fields. Preserve every section above — modify narrative under `# What does this implement/fix?`, never by deleting the structural headings.

**`change_type` workflow input** — comma-separated string, but upstream now enforces a single ticked box (see above) — pass one value. Whitespace and case are normalised. Auto-forced to `new-provider` when `PREV_TAG` is empty (first submission).

## Reverse-sync Channel

The inverse of forward-sync: contributors PR against the inlined provider tree
in `music-assistant/server`; the radar detects merged ones and auto-opens a
**draft** PR porting them back into the provider repo (the source of truth).

`reverse-sync-radar.yml` (cron every 2h + `workflow_dispatch`, uses
`FORK_SYNC_PAT`) runs `scripts/reverse_sync_radar.py` over every provider in
`providers.yml`. Two passes per provider:
- **Pass A (anchor):** latest upstream SHA on the provider path → `last_synced_sha`
  in state (consumed by the P0 guard below).
- **Pass B (action):** merged PRs touching `music_assistant/providers/<domain>/`
  **or** `tests/providers/<domain>/` → `reverse_sync_open_pr.open_reverse_pr`.

### Scripts

| Script | Role |
|--------|------|
| `reverse_sync_radar.py` | Two-pass radar; iterates `providers.yml`; updates+commits `state/reverse-sync.json` |
| `reverse_sync_open_pr.py` | Fetch → reverse-transform → dedup → apply → scaffold → draft PR |
| `reverse_sync_state.py` | Load/save the committed state file |
| `reverse_sync_notify.py` | Open/update a deduped issue in THIS hub (never upstream) |
| `check_upstream_ahead.py` | P0 preflight-guard core (content-hash compare) |
| `_transform.py` | Single source of truth for the path/import transform |

### Opener pipeline (and the non-obvious constraints — each is a fixed bug; don't regress)

1. **Fetch diff via REST, not `gh pr diff`** — `_fetch_pr_diff` uses
   `gh api repos/.../pulls/<n>` with `Accept: application/vnd.github.diff`.
   `gh pr diff` emits a *per-commit* patch (a file appears once per commit),
   which breaks reverse-apply on multi-commit PRs.
2. **Reverse the transform** (`_transform.reverse_diff`), then **strip
   maintainer-owned files** (`_drop_maintainer_owned`: `VERSION`,
   `translations/en.json`) — the PR body promises these are untouched.
3. **Dedup** — skip if already ported: a fast `git apply --check --reverse`
   probe, then `_already_present`, which checks every **added line** is present
   in the provider file (NOT whole-file equality — the SoT advances past a
   merged PR's base, so whole-file compare never matches).
4. **Committer identity** — the opener sets a bot `user.name`/`user.email` on
   the clone; CI clones have none and `git commit` would fail rc=128.
5. **Apply** — `git apply --3way` **alone** (NOT `--3way --reject`; git rejects
   that combination). `_fetch_upstream_base` first fetches the upstream PR's
   base commit into the (shallow) clone so `--3way` has the pre-image blobs —
   without them it reports "lacks the necessary blob" and rejects whole files,
   producing a scaffold-only PR. Conflicts → `<<<<<<<` markers left in-tree.
6. **Push** with plain `--force` (not `--force-with-lease`: a fresh
   `--branch dev` clone has no remote-tracking ref for the bot-owned
   `reverse-sync/*` branch to lease against).
7. **Open draft PR** (`_create_draft_pr`) with the upstream contributor as
   `Co-authored-by`, labels `reverse-sync` + (`needs-human` if conflicts).
   Retries **without labels** if they don't exist in the provider repo (labels
   are distributed via `labels.yml.j2`, but the PR matters more).

### Other behavior

- **Pagination:** `_merged_prs` pages until the `pulls_cursor` watermark
  (`MAX_PAGES=10`) so a provider PR buried past page 1 on the high-traffic
  upstream isn't missed.
- **Failure isolation:** per-PR and per-provider failures are caught so one
  failure doesn't abort the run; a failed port is NOT marked handled (stays
  re-discoverable; cursor held below the earliest failure) and raises an
  incident issue (`incident:reverse-sync`).
- **State** `state/reverse-sync.json`: `{ "<domain>": { last_synced_sha,
  handled_prs:[], pulls_cursor, digest_issue } }`. To re-process a PR, remove it
  from `handled_prs` and set `pulls_cursor` below its `updated_at`.
- **AI-Policy rule 2:** no reverse-sync script ever opens/comments/pushes/closes
  in `music-assistant/*` — only read-only `gh api` GET / `gh pr view`/`diff` and
  read-only `git fetch`. Enforced by `tests/test_ai_policy_readonly.py`.

### P0 forward-sync guard

`reusable-sync-to-fork.yml` runs `check_upstream_ahead.py` before its destructive
`rsync --delete`: if upstream is ahead of the provider repo on a non-ignored path
(`VERSION` / `translations/en.json` ignored) the job fails closed (also fails on
an empty domain). Override with the `ack_upstream_ahead=true` dispatch input.

The guard is direction-aware (issues #104/#113): a differing file is only
"upstream ahead" if upstream's copy matches **none** of the provider repo's
recent release-tag states (`drop_provider_ahead`, newest-first tag walk, capped
at `--max-baseline-tags`, default 30; each tag snapshot goes through the same
boundary transforms). Upstream merely lagging behind our releases — every
normal release with not-yet-upstreamed work — no longer trips the guard. No
tags / no git metadata → fail-closed (every difference flagged); the workflow
checks out the provider repo with `fetch-depth: 0` so tags are present.

A second pass (`drop_already_ported`, msx_bridge conftest fallout) unblocks
the reverse-port limbo: after a contributor edit merges upstream AND is
ported into the provider repo, upstream's copy equals neither any tag (it
carries the edit) nor HEAD (which moved on) — the tag walk alone would block
until the next upstream provider PR merges. A file is dropped when, vs some
recent tag state, every upstream-added line is present in HEAD and every
upstream-removed line is absent (same idea as the reverse opener's
`_already_present`); any fetch/tag/HEAD gap keeps it flagged (fail-closed).
Disable with `--no-ported-check`.

The path/import transform (`_transform.py`) is the single source of truth: it
canonicalizes the seven `provider.` import shapes (`from provider.` /
`from provider import` / `import provider.` / `import provider as X` /
`import provider` / `"provider.` / `'provider.`). **Both** forward `sed` blocks
— `reusable-sync-to-fork.yml` and `upstream-pr.yml.j2` — are pinned to it by
`tests/test_forward_sed_parity.py` (change all three together). The
rewrite-safe gate (`check_rewrite_safe_tests.py`) flags only **non-aliased**
`import provider[.X]` (the body's bare `provider.` access can't be rewritten);
the aliased `import provider.X as alias` is safe because the import line is
rewritten and the body uses the alias.

## Jinja2 Template Conventions

Templates in `wrappers/` receive these variables: `domain`, `display_name`, `manifest_path`, `provider_path`, `provider_type`, `locale`, `repo`, `default_branch`, `codespell_ignore_words`.

GitHub Actions expressions (`${{ }}`) must be wrapped in `{% raw %}...{% endraw %}` blocks to prevent Jinja2 from interpreting them.

**Whitespace gotcha:** `{% if cond %}` on its own line emits a blank line when the condition is False. Use `{%- if cond %}` (dash before `%`) to suppress it — the `-` strips the preceding `\n` unconditionally, for both True and False branches.

## Skipping Wrappers Per Provider

Add `skip_wrappers` to a provider entry in `providers.yml` to exclude specific templates:

```yaml
skip_wrappers:
  - docs.yml.j2
  - docs/known-issues.md.j2
```

Use this when a provider already has a custom version of a file, or when a template doesn't apply (e.g. `player_provider` skips music-specific docs).

## Template Validation

`python3 scripts/validate_templates.py` — checks all top-level `wrappers/*.j2` for syntax errors, missing trailing newline, and double trailing newlines. **Does not check `wrappers/docs/*.j2` subdirectory templates.** Must be updated when new context variables are added.

**Distribute runs immediately after merge** — `distribute.yml` triggers within seconds of a push to `main`. CI failures in provider repos appear almost immediately. Test templates locally before merging:

```bash
python3 scripts/validate_templates.py

# Render a specific template without GitHub auth:
python3 - <<'EOF'
from pathlib import Path; import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
env = Environment(loader=FileSystemLoader('wrappers'), undefined=StrictUndefined, keep_trailing_newline=True)
registry = yaml.safe_load(Path('providers.yml').read_text())
provider = next(p for p in registry['providers'] if p['domain'] == 'kion_music')
ctx = {k: provider.get(k, '') for k in ['domain','display_name','manifest_path','provider_path','provider_type','locale','codespell_ignore_words']}
ctx.update(repo=provider['repo'], default_branch=provider['default_branch'], all_providers=registry['providers'])
print(env.get_template('docs/index.md.j2').render(**ctx))
EOF
```

## Secrets

`FORK_SYNC_PAT` — a PAT with `contents:write` (and `pull-requests:write` on the
provider repos) — must be set in:
- Each provider repo (for sync-to-fork and release workflows)
- This repo (for `distribute.yml` to create PRs in provider repos, **and** for
  `reverse-sync-radar.yml` to clone provider repos, push `reverse-sync/*`
  branches, and open reverse PRs)

## Adding a Provider

1. Add entry to `providers.yml`
2. Push to `main` — `distribute.yml` auto-creates PRs with wrapper files in the new repo
3. Set `FORK_SYNC_PAT` secret in the new provider repo

## Dev Workspace

`scripts/dev-workspace.py` creates a shared development workspace with one `trudenboy/ma-server` fork and a common `.venv` (Python 3.12, uv). Each provider is symlinked into the server's providers directory.

```bash
# Create workspace with all providers
python3 scripts/dev-workspace.py init --dir ~/ma-workspace --all

# Add a single provider
python3 scripts/dev-workspace.py add yandex_music --dir ~/ma-workspace

# Update all repos + deps
python3 scripts/dev-workspace.py update --dir ~/ma-workspace

# Start MA server
python3 scripts/dev-workspace.py run --dir ~/ma-workspace

# Show status
python3 scripts/dev-workspace.py status --dir ~/ma-workspace
```

Provider repos can also use `./scripts/setup.sh --workspace ~/ma-workspace` to link into an existing workspace instead of creating a standalone venv.
