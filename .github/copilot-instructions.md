# Copilot Instructions

## What This Repo Does

Central infrastructure for Music Assistant custom providers. Manages two things:
1. **Shared reusable workflows** (`.github/workflows/reusable-*.yml`) — called by all provider repos via `uses:`. Changes take effect immediately across all provider repos without any PRs.
2. **Wrapper file distribution** — Jinja2 templates in `wrappers/` rendered per-provider and pushed as PRs by `scripts/distribute.py`.

`distribute.yml` triggers within seconds of a push to `main` when `wrappers/` or `providers.yml` changes. **Always validate templates locally before merging.**

## Commands

```bash
# Install dependencies
pip install jinja2 pyyaml

# Validate all top-level wrappers/*.j2 templates (syntax, trailing newline)
python3 scripts/validate_templates.py

# Dry run distribute (no PRs created)
GH_TOKEN=<your-pat> python3 scripts/distribute.py --dry-run

# Run distribute (creates PRs in all provider repos)
GH_TOKEN=<your-pat> python3 scripts/distribute.py

# Render a single template locally (no GitHub auth required)
python3 - <<'EOF'
from pathlib import Path; import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
env = Environment(loader=FileSystemLoader('wrappers'), undefined=StrictUndefined, keep_trailing_newline=True)
registry = yaml.safe_load(Path('providers.yml').read_text())
provider = next(p for p in registry['providers'] if p['domain'] == 'kion_music')
ctx = {k: provider.get(k, '') for k in ['domain','display_name','manifest_path','provider_path','provider_type','locale']}
ctx.update(repo=provider['repo'], default_branch=provider['default_branch'], all_providers=registry['providers'])
print(env.get_template('test.yml.j2').render(**ctx))
EOF

# Run pre-commit hooks
pre-commit run --all-files
```

`validate_templates.py` only checks top-level `wrappers/*.j2` — not `wrappers/docs/*.j2`.

## Architecture

### providers.yml — Single Source of Truth

All provider metadata lives here. `distribute.py` reads it to know which repos get which templates.

```yaml
providers:
  - domain: my_provider          # matches manifest.json domain field
    repo: trudenboy/ma-provider-my-provider
    default_branch: dev
    manifest_path: provider/manifest.json
    provider_path: provider/
    provider_type: music_provider  # or player_provider
    locale: ru                   # affects bilingual MkDocs config
    legacy_files:                # optional: deleted from provider repo on distribute
      - .github/workflows/old.yml
    skip_wrappers:               # optional: templates not pushed to this provider
      - docs/known-issues.md.j2
```

`provider_type` controls `reusable-test.yml` CI behavior:
- `music_provider` — lighter CI using upstream `music-assistant/server`
- `player_provider` — heavier CI using `trudenboy/ma-server` fork (ruff + mypy)
- `server_fork` — skips most wrappers; used for `trudenboy/ma-server` itself

### Template Variable Context

Templates receive: `domain`, `display_name`, `manifest_path`, `provider_path`, `provider_type`, `locale`, `repo`, `default_branch`, `all_providers`.

`StrictUndefined` is used — referencing an undefined variable raises an error at render time.

### Incident Pipeline

```
test.yml fails → reusable-report-incident → GitHub Issue (incident:ci + priority:high)
                                                    ↓
                                         issue-project.yml → MA Ecosystem board
                                                    ↓
                              add label "copilot" → copilot-triage → @copilot PR
```

## Key Conventions

### Jinja2 in GitHub Actions Templates

GitHub Actions expressions (`${{ }}`) **must** be wrapped in `{% raw %}...{% endraw %}` to prevent Jinja2 from interpreting them.

### Whitespace in Conditionals

`{% if cond %}` on its own line emits a blank line when the condition is False. Use `{%- if cond %}` (leading dash) to suppress it. The dash strips the preceding newline unconditionally.

### skip_wrappers

Add `skip_wrappers` to a provider entry to exclude specific templates from distribution. Use when a provider has a custom version of a file, or when a template doesn't apply (e.g., `player_provider` skips `docs/known-issues.md.j2`).

### Adding a Provider

1. Add entry to `providers.yml`
2. Push to `main` — `distribute.yml` auto-creates PRs in the new repo
3. Set `FORK_SYNC_PAT` secret in the new provider repo

### Secrets

`FORK_SYNC_PAT` (PAT with `contents:write`) must be set in:
- Each provider repo (for sync-to-fork and release workflows)
- This repo (for `distribute.yml` to create PRs in provider repos)
