# AI Policy

This document describes how AI assistants (LLMs, coding agents, review bots)
may be used in the `trudenboy/ma-provider-tools` ecosystem and how that aligns
with the upstream Open Home Foundation policy that governs
`music-assistant/server` — the project our providers are eventually inlined
into.

## Authoritative upstream policy

The upstream policy lives at
[`music-assistant/.github/AI_POLICY.md`](https://github.com/music-assistant/.github/blob/main/AI_POLICY.md).
It is binding for any contribution that lands in a Music Assistant repository,
including any pull request opened against `music-assistant/server` by our
`upstream-pr.yml` workflow. When this document and the upstream policy
disagree, the upstream policy wins.

The short form:

- AI may be used as a tool.
- The human contributor is responsible for every line they submit and must be
  able to explain it without AI help.
- Autonomous agents that open PRs / issues are not allowed.
- AI-generated text posted unreviewed on issues, PRs, or review threads is not
  allowed.

## Why we have a local policy

The provider fleet (`trudenboy/ma-provider-*`) is a multi-repo development
sandbox. Each provider is designed to be inlined into
`music_assistant/providers/<domain>` upstream — that is the target shape, not
a possibility. Our local CI, distribution workflow, and review process exist
to make sure that when a provider crosses the upstream boundary, every change
is something a contributor can stand behind under upstream rules.

This document covers two things the upstream policy doesn't address directly:

1. The infrastructure-sync PRs that `ma-provider-tools` opens **inside its own
   ecosystem** (provider repos, this repo). These are not contributions to
   upstream and are governed by the rules in this document.
2. The boundary at which a provider release becomes an upstream PR (via
   `wrappers/upstream-pr.yml.j2`). Crossing that boundary must satisfy the
   upstream policy in full.

## Local rules for our ecosystem

### 1. Boundary: upstream is read-only by default

No AI assistant may open a PR, push a branch, comment on an issue, reply to a
review comment, or close anything in `music-assistant/server`,
`music-assistant/models`, `music-assistant/frontend`, or any other
`music-assistant/*` repository **except** through the
`upstream-pr.yml.j2`-rendered workflow, which:

- Runs only on a stable provider release (gated by a `VERSION` bump landing on
  `default_branch`).
- Opens the PR as `--draft`.
- Embeds a human-attestation checklist in the PR body that the contributor
  must check before requesting review.
- Strips any `Co-Authored-By: Claude` / AI co-author trailers from the merge
  commit message before push, so upstream history does not carry AI
  attribution.

A human contributor lifts the `draft` state and is the named author of the
upstream PR. From that point on the upstream policy governs all
communication on the PR — see rules 3 and 4 below.

### 2. Inside our own ecosystem: AI as a tool, human as owner

In `trudenboy/ma-provider-tools` and each `trudenboy/ma-provider-*` repo, AI
assistants may write code, draft commit messages, and draft PR descriptions.
They may not merge their own PRs. Every PR has a human owner who can explain
every change. A PR that consists of unreviewed AI output should be closed.

The `distribute.yml`-generated wrapper-sync PRs are an exception: they
contain only mechanically-rendered template output, are auto-merged, and
carry no human-attestation requirement. They only flow **inside** our
ecosystem (this repo → provider repos) and never cross into
`music-assistant/*`.

### 3. AI replying to humans on PRs and issues: not allowed

A contributor must respond to questions from human reviewers (upstream
maintainers, our own maintainers, external contributors) in their own words.
AI may be used to improve grammar or clarity, but the substance must be the
contributor's. This applies on upstream PRs and on our own PRs alike.

### 4. AI replying to AI on PRs and issues: allowed

GitHub Copilot, code-scanning bots, and similar automated review tools post
comments that are themselves AI output. A contributor may use an AI assistant
to triage and reply to those comments — the conversation is AI ↔ AI and no
human reviewer time is being consumed.

Constraints:

- The contributor must still apply judgement to whether the AI comment is
  correct, and AI-drafted replies must be read before posting.
- If a human reviewer chimes into the same thread, rule 3 takes over for
  every reply after that point.
- Replies to AI on **upstream** PRs are still bound by the upstream policy's
  requirement that unreviewed AI output not be posted — a reviewed AI reply
  is fine, an unreviewed dump is not.

### 5. Disclosure inside our ecosystem

AI co-author trailers (`Co-Authored-By: Claude ...`) are encouraged on
commits inside our ecosystem as honest disclosure. They are stripped at the
upstream boundary (rule 1) so they don't pollute `music-assistant/server`
history with attribution that upstream policy does not require.

### 6. Translation and non-native English speakers

AI translation of comments is fine — see the upstream policy. Keep the
original text in a `<details>` block, both upstream and in our own repos.

## Enforcement

- Upstream PRs that fail the human-attestation checklist or that leak AI
  co-author trailers will be closed and reopened only after the contributor
  fixes them locally.
- Provider-repo PRs that look like unreviewed AI output (no human owner who
  can explain the diff in their own words, or AI-drafted replies to human
  reviewer questions) will be closed.
- Repeated violations will result in the contributor being blocked from
  using the `upstream-pr.yml` workflow on the affected provider until
  manually re-enabled by a maintainer.

## Where to look

- Upstream policy: `music-assistant/.github/AI_POLICY.md`.
- Per-provider summary: each provider repo carries an `AI_POLICY.md` rendered
  from `wrappers/AI_POLICY.md.j2` in this repo.
- Day-to-day operational rules for AI in a provider repo:
  `CLAUDE.md` (rendered from `wrappers/CLAUDE.md.j2`), section *AI Policy
  Alignment*.
- The upstream-boundary mechanics: `wrappers/upstream-pr.yml.j2`.
