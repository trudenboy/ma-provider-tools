# Reverse-sync channel — design

**Issue:** [trudenboy/ma-provider-tools#93](https://github.com/trudenboy/ma-provider-tools/issues/93)
**Date:** 2026-06-30
**Scope:** P0 forward-sync preflight guard **+** P1 automatic reverse-sync after merge (single design).
**Status:** approved (brainstorm) → ready for implementation plan.

## Problem

Contributors discover provider code inlined in `music-assistant/server`
(`music_assistant/providers/<domain>/`) and open PRs there. The provider repos
(`trudenboy/ma-provider-*`) are the source of truth, and automation only flows
one way:

```
provider repo (SoT) ──forward-sync (rsync --delete)──▶ ma-server fork ──upstream-pr──▶ music-assistant/server
        ▲                                                                                        │
        └──────────────────────── NO reverse channel ◀──────────── contributors PR here ────────┘
```

Two failures result:

1. **Data loss.** `reusable-sync-to-fork.yml` does `rsync -av --delete`. A
   forward-sync that runs between an upstream merge and a hand reverse-sync
   silently reverts the contributor's work upstream.
2. **No detection.** Inbound PRs are noticed by luck (a maintainer ping).

## Hard constraints (from issue #93)

- **AI-Policy rule 2** (`wrappers/AI_POLICY.md.j2:30`): no AI/automation may
  open, comment on, push to, or close anything in `music-assistant/*`. **All
  upstream API access in this design is read-only (GET).** Every write lands in
  a provider repo or in this hub.
- **Fork model:** forward-sync is a destructive tree replacement; any
  un-reverse-synced upstream commit on our path is lost on the next sync.
- **VERSION is maintainer-owned** — automation must never bump it. Likewise
  `translations/en.json`.
- `sync-to-fork` is `workflow_dispatch` (not push-triggered) → a natural gate
  for a preflight check.
- CODEOWNERS request to upstream is **explicitly out of scope** (maybe later) —
  detection is therefore purely poll-based from this hub.

## Decisions (locked during brainstorm)

| # | Decision |
|---|---|
| 1 | **Trigger model = hybrid.** `commit-on-default` (path-filtered) → `last_synced_sha` anchor for the P0 guard + backstop detector. `merged-PR` → primary reverse-sync trigger (native author credit, 1:1 logical change, idempotency by handled-PR set). One cron, two passes, shared committed state. |
| 2 | **Apply/conflict = snapshot three-way with verified outcomes.** The combined REST diff identifies touched paths; normalized upstream base/head snapshots are compared with the current provider tree. Open a draft only when it contains applied changes or real diff3 markers; skip full dedup and fail closed on incomplete or unsafe structural outcomes. Verified conflicts get `[needs-human]` in the title plus the advisory label. |
| 3 | **Scope = P0 guard + P1 reverse-sync together** (they share the anchor and state). |
| 4 | **Shared transform module** `scripts/_transform.py` is the single source of truth for path + import mapping. Forward-sync (`reusable-sync-to-fork.yml` and `upstream-pr.yml.j2`) is refactored to call it `forward`; reverse calls it `reverse`. |
| 5 | **P0-guard ack = `workflow_dispatch` input** `ack_upstream_ahead` (default `false`). `true` → guard logs a warning and proceeds. |
| — | **State store = `state/reverse-sync.json`** committed to this hub (pattern mirrors `public/badges/`). |

## Components

All in the hub (`ma-provider-tools`).

| Component | File | Role |
|---|---|---|
| Radar (cron + dispatch) | `.github/workflows/reverse-sync-radar.yml` | Cron every 2h + manual. Drives `reverse_sync_radar.py`. |
| Radar logic | `scripts/reverse_sync_radar.py` | Iterates `providers.yml`, read-only polls upstream, two passes, updates state, dispatches the opener. |
| Reverse-PR opener | `scripts/reverse_sync_open_pr.py` | Normalize upstream base/head snapshots, three-way merge touched files, open a draft PR in the provider repo. |
| Transform module | `scripts/_transform.py` | Single source of truth for path + import mapping (`forward` / `reverse`). |
| State | `state/reverse-sync.json` | `{ "<domain>": { last_synced_sha, handled_prs: [], pulls_cursor, digest_issue } }`. Committed. |
| P0 preflight guard | edit in `.github/workflows/reusable-sync-to-fork.yml` + input in `wrappers/sync-to-fork.yml.j2` | Block `rsync --delete` when upstream is ahead of the provider repo. |

## Transform module (`scripts/_transform.py`)

Single source of truth. Mirrors the three `sed` rules currently inline in
`reusable-sync-to-fork.yml`:

| Forward (`provider/` → upstream) | Reverse (inverse) |
|---|---|
| path `provider_path` → `music_assistant/providers/<domain>/` | strip-prefix back to `provider_path` |
| `from provider.` → `from music_assistant.providers.<domain>.` | back |
| `from provider import` → `from music_assistant.providers.<domain> import` | back |
| `"provider.` (mock.patch literals) → `"music_assistant.providers.<domain>.` | back |
| tests → `tests/providers/<domain>/` | back to provider-repo `tests/` |

The reverse transform applies to **both** the diff path headers (`a/`, `b/`)
and the file content (import lines, mock literals). Tests are ported
symmetrically — forward-sync syncs `tests/`, so reverse must too, or the
contributor's test changes are lost.

**Refactor:** `reusable-sync-to-fork.yml` and `upstream-pr.yml.j2` switch their
inline `sed` to `python3 scripts/_transform.py forward …` so forward and
reverse can never drift. Round-trip invariant: `reverse(forward(x)) == x`.

## Radar — two passes (`reverse_sync_radar.py`)

Cron every 2h + `workflow_dispatch`. For each provider in `providers.yml`
(`domain`, `provider_path`, `repo`, `default_branch`):

### Pass A — anchor / backstop (commit-on-default, read-only)

```
GET /repos/music-assistant/server/commits
      ?path=music_assistant/providers/<domain>&sha=<default>
  → head_sha = latest commit touching the path
  → state[domain].last_synced_sha = head_sha
```

Pass A only records the anchor (latest upstream SHA on the path). It takes no
action itself; the anchor is consumed by the P0 guard. Only the newest SHA is
needed — no detailed commit walk.

### Pass B — action (merged-PR)

```
GET /repos/music-assistant/server/pulls?state=closed&base=<default>&sort=updated
  → for each merged PR newer than state[domain].pulls_cursor:
       GET /pulls/{n}/files → prefix music_assistant/providers/<domain>/ present?
       n in state[domain].handled_prs?              → skip (idempotency)
       author is our bot / upstream-pr?             → skip (forward-sync echo)
       diff already present in provider-repo HEAD?  → skip (universal no-op dedup)
  → else: invoke reverse-PR opener
  → on success: state[domain].handled_prs.append(n)
  → advance state[domain].pulls_cursor to max updated_at seen
```

**Echo filter is double** (our own upstream-PRs merge into the same path):
(1) PR author (our bot / `upstream-pr` is recognizable), (2) backstop —
the normalized snapshot merge produces only `already_present` outcomes.
Either is sufficient to skip.

**State commit:** at the end of the run, `git add state/ && commit && push`
(like badges). `concurrency` group prevents overlapping cron runs.

**Targeted retry:** `workflow_dispatch` accepts `retry_domain` and positive
`retry_pr` together. The radar validates the registry domain and confirms that
the upstream PR exists and is merged before reading state. It then bypasses
cursor/handled filtering only for that pair, uses the ordinary processing path,
idempotently marks a durable result handled, and leaves `pulls_cursor` unchanged.

## Reverse-PR opener (`reverse_sync_open_pr.py`)

Runs in a checkout of the provider repo (`default_branch`). Input: one inbound
PR number + domain.

1. **Fetch manifest and snapshots (read-only upstream):** request the PR's
   combined REST diff (`Accept: application/vnd.github.diff`) to identify its
   touched paths, then fetch the immutable base and head commits. Capture
   `PR.user.login` for credit.
2. **Normalize snapshots** via `scripts/_transform.py`: map base/head source and
   test paths into provider layout and reverse test imports in both snapshots.
3. **Merge best-effort with verified outcomes:**
   ```
   git checkout -b reverse-sync/<domain>-pr<n>
   # For every touched file compare BASE / current provider / upstream HEAD.
   # Clean drift is merged with git merge-file --diff3; overlaps leave markers.
   git add -A
   git commit -m "reverse-sync: port music-assistant/server#<n>" \
     --trailer "Co-authored-by: <author> <id+login@users.noreply.github.com>"
   ```
   `OURS == HEAD` is already present; `OURS == BASE` takes the normalized head;
   other text edits use a real diff3 merge. Structural text conflicts such as
   modify/delete are rendered with markers. In particular, a file that existed
   in `BASE`, is absent from the provider, and changed in upstream `HEAD` is a
   modify/delete conflict (the `#5782` case), not a clean materialization.
   Divergent binary/symlink states, ambiguous renames, missing snapshots,
   incomplete classification, or unexpected paths abort before scaffold/push/PR.
   The algorithm does not depend on patch index SHAs, `git apply`, or `.rej`.
4. **Scaffold (issue P1):** `specs/inprogress/reverse-sync-pr<n>.md`
   (WIP=1) + a `CHANGELOG` stub. **VERSION and `translations/en.json` are NOT
   committed** (maintainer-owned); if the contributor changed them upstream,
   note it in the PR body for manual review.
5. **Open or safely update a draft PR in the provider repo:** before resetting
   the deterministic branch, an existing PR must be an untouched draft with one
   bot-generated reverse-sync commit and scaffold-only files. Human commits or
   provider/test changes are never overwritten. Safe retries preserve the PR
   number, URL, comments, and review history.
   ```
   gh pr create --repo <repo> --base <default_branch> --draft
     --title "[needs-human] reverse-sync: <upstream PR title> (#<n>)"  # conflict
     --body <upstream link + credit + checklist>
   ```
   The body lists actual conflict files and only artifacts that exist. Labels
   are applied through provider REST endpoints after PR creation/update;
   `reverse-sync` is mandatory and `needs-human` is added for verified
   conflicts. The title prefix is the durable fallback when label application
   fails; a deduped hub incident records failed labels without discarding the
   useful provider PR.

## P0 preflight guard (`reusable-sync-to-fork.yml`)

New step **before** "Sync provider files into integration/dev" (the
`rsync --delete` at ~line 113):

```
1. Read expected last_synced_sha from state/reverse-sync.json (raw.githubusercontent from hub).
2. GET /repos/music-assistant/server/commits?path=music_assistant/providers/<domain>  (read-only)
     → upstream_head.
3. If upstream content on the path differs from the provider repo on any path
   OUTSIDE the ignore-list, AND that change is not one of our own outgoing syncs:
     → FAIL the job with a clear message + link to the reverse-sync issue,
       unless ack_upstream_ahead == true.
```

**Comparison = file content-hash**, not commit SHA — robust to squash/rebase
and to our own forward-sync echo. "Upstream ahead" = a file under the
ignore-filtered path whose upstream content differs from the provider repo
**and** is not among our outgoing changes.

**Ignore-list:** `VERSION`, `translations/en.json`, pure-format (ruff) diffs.
These are legally maintainer/upstream-owned and are not "lost work."

**Ack:** new `workflow_dispatch` input `ack_upstream_ahead` (bool, default
`false`) in `wrappers/sync-to-fork.yml.j2`. `true` → guard logs a warning and
proceeds (maintainer's explicit "sync over it" button).

## Notifications (all in hub, AI-policy-safe)

Reuses the existing `report-failure` pattern (open/update issue, dedup by
label+title).

| Event | Channel |
|---|---|
| Merged inbound PR → reverse-sync opened | the draft PR in the provider repo **is** the notice; plus a line in the digest issue |
| Conflict reverse-PR (`needs-human`) | same draft PR + flagged ⚠ in the digest |
| P0-guard blocked a forward-sync | fail job + open/update incident issue (label `incident:reverse-sync`) with run link + instruction (do a reverse-sync **or** rerun with `ack_upstream_ahead=true`) |
| Radar failed to open a PR (merge/auth) | incident issue, same label |

Digest issue is a single updatable hub issue (`state[domain].digest_issue`
holds its number) — no spam. Zero writes to `music-assistant/*`.

## Edge cases

- **Forward-sync echo** → double filter (PR author + snapshot dedup).
- **Squash-merge upstream** → use the combined REST diff as a PR-level path
  manifest and fetch the recorded base/head commits; never map merge commits.
- **PR touches multiple providers** → process per `domain`, one reverse-PR each.
- **PR touches provider path + shared upstream code** (`tools/_common.py`) →
  port only the slice under `music_assistant/providers/<domain>/`; prefix-filter
  the diff, ignore the rest.
- **PR closed/reopened** → `handled_prs` is the final dedup.
- **GitHub API rate-limit** → watermark (`pulls_cursor`) + `per_page`; pass B
  never lists the full history.

## Testing (maps to issue acceptance criteria)

- `scripts/_transform.py` — round-trip units: `reverse(forward(x)) == x` over
  paths, imports, mock literals, test files.
- **P0-guard** — fixture where the upstream path is ahead → job fails
  (**acceptance #1**); fixture where only `VERSION` differs → does NOT fail
  (ignore-list).
- **Radar** — fixture with a merged PR → reverse-PR command formed, contributor
  in `Co-authored-by`, VERSION/translations untouched (**acceptance #3**).
- **AI-policy** — grep test asserting the radar/opener never call
  `gh pr create/comment/review` or push against `music-assistant/*`
  (**acceptance #4**).
- **Registry-driven** — everything iterates `providers.yml`; onboarding a new
  provider needs no per-repo wiring (**acceptance #5**).

## Out of scope (this design)

- Upstream CODEOWNERS request and the provider-dir pointer note (issue P0
  detection items) — deferred, maybe later.
- P2: automated Decision layer (mechanical-regenerate vs feature-scaffold) and
  cross-PR conflict-surface pre-checks.

---

## Implementation notes (post-build, live-validated)

The channel was built subagent-driven, then validated against live
`music-assistant/server` PRs, which surfaced several constraints the brainstorm
didn't anticipate. Each is now encoded in code + tests; documented here and in
the repo `CLAUDE.md` so future edits don't regress them.

- **Diff source:** the opener fetches the combined diff via
  `gh api .../pulls/<n>` with `Accept: application/vnd.github.diff`, NOT
  `gh pr diff` (which emits a per-commit series instead of one deterministic
  touched-path manifest).
- **Maintainer-owned strip:** `VERSION` / `translations/en.json` are removed
  from the touched-path manifest before snapshot merge, not merely omitted from
  scaffold generation.
- **Dedup is a three-way outcome:** normalized upstream base/head snapshots are
  compared with the provider tree. This preserves independent provider changes
  while recognizing an already-landed upstream change.
- **Committer identity:** the opener sets a bot `user.name`/`user.email` on the
  clone (CI clones have none; `git commit` fails rc=128 otherwise).
- **Verified snapshot merge:** each touched path has one immutable normalized
  base/head pair and exactly one outcome: already present, applied, or conflict
  with real diff3 markers. Missing/incomplete outcomes and unexpected paths are
  fatal before scaffold/push/PR, preventing scaffold-only PRs.
- **Push:** new branches use a normal create-only push; verified retries use an
  explicit expected-head `--force-with-lease`, so races fail without overwriting
  human work.
- **PR/label durability:** an untouched bot scaffold draft can be safely updated
  in place; any human change fails closed before force-push. Labels use provider
  REST endpoints, missing labels are created and retried once, and residual
  failures produce a deduped hub incident while the useful PR remains handled.
- **Pagination:** `_merged_prs` pages until the cursor (`MAX_PAGES=10`) so PRs
  buried past page 1 on the high-traffic upstream aren't missed.

These were tracked as issues #94 (pagination), #95 (dedup drift), #97 (`--3way`),
plus the pre-existing #77 (rewrite-safe gate) — all closed. End-to-end validation:
`music-assistant/server#4313` → `trudenboy/ma-provider-mcp#152` carried the real
contributor delta with genuine conflict markers.
