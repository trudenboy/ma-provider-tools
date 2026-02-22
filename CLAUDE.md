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
| `.github/workflows/distribute.yml` | Runs `distribute.py` on push to `main` when wrappers or registry changes |

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
    provider_type: music_provider  # or player_provider
    legacy_files:                # optional: files to delete during distribution
      - .github/workflows/old.yml
```

`provider_type` controls CI behavior in `reusable-test.yml`:
- `music_provider` — uses upstream `music-assistant/server` (lighter CI)
- `player_provider` — uses `trudenboy/ma-server` fork with ruff + mypy (heavier CI)

## Jinja2 Template Conventions

Templates in `wrappers/` receive these variables: `domain`, `display_name`, `manifest_path`, `provider_path`, `provider_type`, `locale`, `repo`, `default_branch`.

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
ctx = {k: provider.get(k, '') for k in ['domain','display_name','manifest_path','provider_path','provider_type','locale']}
ctx.update(repo=provider['repo'], default_branch=provider['default_branch'], all_providers=registry['providers'])
print(env.get_template('docs/index.md.j2').render(**ctx))
EOF
```

## Secrets

`FORK_SYNC_PAT` — a PAT with `contents:write` — must be set in:
- Each provider repo (for sync-to-fork and release workflows)
- This repo (for `distribute.yml` to create PRs in provider repos)

## Adding a Provider

1. Add entry to `providers.yml`
2. Push to `main` — `distribute.yml` auto-creates PRs with wrapper files in the new repo
3. Set `FORK_SYNC_PAT` secret in the new provider repo
