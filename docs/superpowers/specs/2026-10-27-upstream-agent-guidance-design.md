# Upstream agent guidance distribution — design

Date: 2026-10-27. Status: implemented in this branch.

## Problem

`music-assistant/server` keeps its architectural, technical and review rules
for AI agents in several files that change almost weekly:

| Upstream file | Read by |
|---|---|
| `AGENTS.md` (`CLAUDE.md` is a symlink to it) | Claude, Codex, Cursor, Gemini |
| `.github/copilot-instructions.md` | Copilot code review |
| `.github/instructions/music-assistant-standards.instructions.md` (~60 review precedents, each citing a PR) | Copilot |
| `.github/instructions/music-assistant-cross-repo.instructions.md` | Copilot |
| `.github/instructions/music-assistant-pr-description.instructions.md` | Copilot |
| `.claude/skills/review-pr/` | Claude |
| `DEVELOPMENT.md` (provider rules, manifest schema) | people and agents |
| `music_assistant/controllers/*/README.md` | on demand |
| org `.github`: `AI_POLICY.md`, `USAGE_POLICY.md`, `CONTRIBUTING.md` | everyone |

Provider repos only received a hand-maintained subset through
`wrappers/CLAUDE.md.j2`:

- The Usage Policy (no exposed stream URLs, no audio on disk, throttle and
  cache API calls, honour `max_concurrent_streams`) was missing, even though
  breaking it closes an upstream PR without discussion.
- Rules on data migrations, provider isolation, cross-repo contracts and the
  review precedents were also missing.
- Only Claude was served. `AGENTS.md` (Codex, Cursor, Gemini) existed in one
  provider. `.github/copilot-instructions.md` existed in ten providers as
  seven different hand-written variants.
- Nothing caught upstream drift.
- Upstream's ruff config ignores `BLE001` and `G004`, so "no silently
  swallowed broad except" and "no f-string log messages" only surfaced at the
  first upstream PR.

## Decisions

1. **Vendored mirror with a lock.** `scripts/sync_upstream_guidance.py` fetches
   a fixed set of files from `music-assistant/server@dev` (resolved to a
   commit SHA) and `music-assistant/.github@main` into `upstream-guidance/`.
   It records the source SHAs and per-file sha256 in
   `upstream-guidance/lock.json`. Controller READMEs are discovered from the
   upstream tree, so a new controller is picked up automatically. `--check`
   exits 1 on drift. The weekly `sync-upstream-config.yml` run also runs this
   sync, so upstream changes arrive as a reviewable PR in this repo. After
   merge, `distribute.yml` rolls them out.
2. **`AGENTS.md` is canonical; `CLAUDE.md` is a symlink to it**, the same as
   upstream. `wrappers/CLAUDE.md.j2` becomes `wrappers/AGENTS.md.j2`. Claude
   Code still auto-loads `CLAUDE.local.md`; `AGENTS.md` points other agents to
   it.
3. **Layout in every provider repo:**

   | Path | Source |
   |---|---|
   | `AGENTS.md` | `wrappers/AGENTS.md.j2`: ecosystem rules, provider-repo mapping, the 40-line upstream MUST list, upstream `AGENTS.md` verbatim (headings demoted) |
   | `CLAUDE.md` | symlink to `AGENTS.md` |
   | `.github/copilot-instructions.md` | `wrappers/.github/copilot-instructions.md.j2`: provider exceptions + upstream file verbatim (demoted) |
   | `.github/instructions/music-assistant-standards.instructions.md` | verbatim |
   | `.github/instructions/music-assistant-cross-repo.instructions.md` | verbatim |
   | `.github/instructions/music-assistant-pr-description.instructions.md` | upstream frontmatter + provider-repo scope note + upstream body |
   | `.claude/skills/ma-review-pr/` | our `SKILL.md`; `REVIEW_STANDARDS.md` and `references/new-provider.md` verbatim |
   | `.claude/skills/ma-upstream-standards/` | our `SKILL.md`; `references/`: `DEVELOPMENT.md`, `USAGE_POLICY.md`, `AI_POLICY.md`, `CONTRIBUTING.md`, `controllers/<name>.md`, all verbatim |
   | `scripts/check_upstream_rules.py` | `wrappers/scripts/check_upstream_rules.py.j2` |

   Verbatim files are copied byte for byte from `upstream-guidance/` through
   `VENDORED_FILES` in `distribute.py`, without going through Jinja. Composite
   files are templates that call the `upstream_file()` global; Jinja does not
   re-parse the content it returns, so upstream text containing `{{` is safe.
4. **Context budget.** `AGENTS.md` carries only the short MUST list plus
   upstream's own `AGENTS.md`. The full precedent catalogue, controller
   READMEs and `DEVELOPMENT.md` load on demand through the
   `ma-upstream-standards` skill. Copilot loads them through `applyTo`.
5. **Conflicts are resolved explicitly** in an "Upstream vs ecosystem
   conventions" section, which wins inside provider repos:
   - Commits and provider-repo PR titles use Conventional Commits. Upstream PR
     titles must not; `upstream-pr.yml` generates them.
   - Provider-repo PR bodies follow the local template. Upstream bodies follow
     the upstream template and the PR-description rules.
   - Copilot replies are allowed in provider repos (AI policy rule 4). Nothing
     is posted to `music-assistant/*`.
   - Paths: `music_assistant/providers/<domain>/` maps to `provider/`, and
     `tests/providers/<domain>/` maps to `tests/`.
6. **Blocking pre-commit gate `check-upstream-rules`** (no warn-only phase).
   It covers review-only upstream rules that no linter enforces. Blocking IO,
   icons, manifests and method order are already run from the upstream clone
   in `reusable-test.yml`, so they are not repeated here.

   | Code | Rule | Upstream precedent |
   |---|---|---|
   | MA001 | new `aiohttp.ClientSession` | server#1817, #2875 |
   | MA002 | broad/bare `except` that neither re-raises nor logs | server#1214, #3722 |
   | MA003 | f-string / `%` / `.format()` log message | server#3147, #1313 |
   | MA004 | discarded `asyncio.create_task` / `ensure_future` / `loop.create_task` | server#3492 |
   | MA005 | `*.music.database` access | server#2502 |
   | MA006 | manifest requirement not pinned with `==` or a git SHA | support#2054 |

   A deliberate exception is allowed with `# ma-allow: MAxxx <reason>` on the
   reported line; a missing reason is itself a violation. The script is pinned
   byte for byte by `check_config_sync.py`, like `check_method_order.py`.

   Calibration (upstream `dev` 291ddf9 and local provider checkouts): a
   cross-provider import rule was dropped, because upstream uses 424 of them
   for base classes and `depends_on`. A strict "any broad except" rule was
   narrowed to "silent swallow", because upstream itself has 362 broad
   excepts and only 48 silent ones. Remaining provider violations: 9 MA001 and
   34 MA002 across station, smarthome, alice, ynison, dlna_receiver and mcp.
   These must be fixed or annotated before the wrapper-sync PR in each of
   those repos can go green.
7. **One-shot migrations in `distribute.py`:**
   - a rendered `CLAUDE.md` (marker present) is replaced by the symlink;
   - a hand-written `CLAUDE.md` with no `CLAUDE.local.md` moves to
     `CLAUDE.local.md` (existing behaviour);
   - a hand-written `AGENTS.md` (no marker) is appended to `CLAUDE.local.md`
     under "Project map (migrated from AGENTS.md)";
   - a hand-written `.github/copilot-instructions.md` (no marker) moves to
     `.github/instructions/provider.instructions.md` with `applyTo: "**"`, so
     Copilot keeps the provider-specific context.

   Distributed files are added with `git add -f`, because several providers
   ignore `.claude/`.
8. **One Jinja environment.** `scripts/_wrapper_env.py` builds the environment
   (the `upstream_file` global plus the `demote_headings` and
   `strip_frontmatter` filters) for `distribute.py`, `render_for_provider.py`
   and `validate_templates.py`. `validate_templates.py` now walks every `*.j2`
   recursively.

## Acceptance criteria

- `sync_upstream_guidance.py --check` passes on the committed mirror; a
  changed upstream file is reported as drift; the lock records the source SHA
  and sha256 for every file.
- Rendering for any provider produces `AGENTS.md`, the Copilot files and both
  skills. `AGENTS.md` contains the Usage Policy, migrations, the MUST list,
  the conventions section and upstream `AGENTS.md` with no second H1.
- `distribute.py` creates `CLAUDE.md` as a symlink to `AGENTS.md`, and
  migrates hand-written `AGENTS.md` and `copilot-instructions.md` without
  losing content.
- `check_upstream_rules.py` flags each of MA001–MA006 and accepts `ma-allow`
  only with a reason; a clean tree passes.
- `check_config_sync.py` fails when `scripts/check_upstream_rules.py` drifts.
- `pytest`, `validate_templates.py` and `validate_providers_yml.py` pass.

## Out of scope

- Fixing the 43 existing violations inside provider repos (separate PR in each
  of the affected repos).
- Replies or PRs in `music-assistant/*` (AI policy rule 2).
