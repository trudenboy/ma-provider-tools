# Ynison upstream guard baseline, 2026-10-02

## Reviewed snapshots

- Provider: [v4.3.4](https://github.com/trudenboy/ma-provider-yandex-ynison/tree/v4.3.4),
  commit `1e0c1bf3a3090e0c6b5bedc4f71ed958933ccc8c`.
- Upstream: [ef4ba48](https://github.com/music-assistant/server/tree/ef4ba48c30edc6225a820b7a581966a775108d99),
  full SHA `ef4ba48c30edc6225a820b7a581966a775108d99`.
- Guard implementation: tools commit `0a677b34cd4784126ef71661ec13bd930d958c22`.

The v4.3.4 release exists, but both forward-sync jobs fail preflight on the
same nine files. Running the actual guard against these immutable snapshots
reproduces that failure. Source and test path histories were checked separately;
the newest commit touching either Ynison root is upstream PR #6526.

## Upstream changes retained in the provider

| Upstream PR | Provider port | Retained behavior |
| --- | --- | --- |
| [#6255](https://github.com/music-assistant/server/pull/6255) | [#165](https://github.com/trudenboy/ma-provider-yandex-ynison/pull/165) | Enumerate `mass.providers`, including internal instances; bind credentials and audio to the exact selected account. |
| [#6382](https://github.com/music-assistant/server/pull/6382) | [#167](https://github.com/trudenboy/ma-provider-yandex-ynison/pull/167) | Preserve the complete `SetupFlowError`, translation metadata and collected selections on retry. |
| [#6595](https://github.com/music-assistant/server/pull/6595) | [#172](https://github.com/trudenboy/ma-provider-yandex-ynison/pull/172) | Stream resolution uses HIGH request priority; radio prefetch and feedback retain caller priority. Required Music Assistant API compatibility updates are retained. |
| [#6526](https://github.com/music-assistant/server/pull/6526) | [#171](https://github.com/trudenboy/ma-provider-yandex-ynison/pull/171) | Real `MusicAssistant.create_task` receives the radio prefetch task name. |

Earlier upstream ports are recorded in the provider's completed specs:
`reverse-sync-pr5773`, `reverse-sync-pr5880`, `reverse-sync-pr5914`,
`reverse-sync-pr5944` and `reverse-sync-pr6026`. Concurrent stream accounting,
queue preservation, stale-session protection, source lifecycle controls,
mandatory connected-player setup and player-derived device names remain in
v4.3.4. The shared auth dependency is already `ya-passport-auth[ma]==2.0.1`.

## Residual differences acknowledged

Files below are in provider-repository layout. Raw upstream blobs were checked
against the forward-transformed provider; reverse-transformed differences were
also inspected to distinguish formatting from behavior.

| File | Reason the upstream snapshot differs |
| --- | --- |
| `provider/__init__.py` | Setup signature formatting and docstring wording; the interface is unchanged. |
| `provider/auth.py` | Unused `PassportClient` re-export and obsolete own/borrow-mode documentation removed; refresh still delegates to the shared auth library. |
| `provider/manifest.json` | Obsolete `segno==1.6.6` QR dependency removed; shared auth pin unchanged. |
| `provider/provider.py` | Linked-only credential adapter replaces own/borrow branches; dynamic PCM sessions, queue ordering/repeat/shuffle, owner/consumer handling and typed error handling extend the retained upstream lifecycle and priority behavior. |
| `provider/setup_flow.py` | Linked-only setup removes QR and remembered local credentials, clears legacy keys and preserves concrete player/account selections; the translated-error retry port is present. |
| `provider/strings.json` | Corresponding linked-only setup and stream-mode descriptions replace own/QR strings. |
| `tests/test_config_entries.py` | Real provider objects check the exact public runtime options, including stream mode, rather than the old auth-options mock. |
| `tests/test_provider.py` | Linked credential tests replace own-mode tests; additional dynamic format, queue, bridge, typed-error, priority and task-name regressions cover retained upstream behavior. |
| `tests/test_setup_flow.py` | Linked-only setup tests replace QR/session fakes and cover dependency absence, account selection, legacy cleanup and full error identity/metadata on retry. |

These architectural changes are intentional provider work, recorded in completed
specs `0005-provider-command-guard-cleanups`, `0006-passthrough-aware-stream-chain-tuning`,
`0007-linked-yandex-auth-only`, `0008-dynamic-max-quality-sessions` and
`0009-ynison-queue-semantics`. Restoring obsolete own/QR auth to make textual
comparison succeed would undo that work. The tag and line-occurrence heuristics
cannot prove all the replacements, so an explicit reviewed baseline is needed.

## Fix and protection

Set only the Ynison registry entry's `upstream_guard_baseline` to the reviewed
full upstream SHA. Existing templates propagate it to both pipeline sync jobs
and the manual sync wrapper. No guard algorithm, source code, version or global
override changes are required.

The existing baseline filter permits a residual path only if its current
upstream blob is exactly the same as the reviewed blob. A new path, a modified
blob or a failed baseline lookup remains blocked. `ack_upstream_ahead` stays
false by default and is not used for recovery.

## Validation

The real guard command, run from the tools checkout, is:

```bash
python scripts/check_upstream_ahead.py \
  --domain yandex_ynison --provider-dir /path/to/provider-v4.3.4 \
  --provider-path provider/ \
  --upstream-ref ef4ba48c30edc6225a820b7a581966a775108d99
```

Without a baseline it exits 1 and lists the nine files above. Adding
`--acknowledged-upstream-ref ef4ba48c30edc6225a820b7a581966a775108d99`
must exit 0 against the same source and upstream snapshots.

`test_ynison_distribution_preserves_guard_for_all_sync_entrypoints` exercises
the real distributor with the registry. It fails before the registry fix and
checks the precise SHA in all three sync entrypoints plus preservation of the
manual override's false default. Existing guard tests cover changed/new blobs,
source and test paths, lookup failure and invalid SHA rejection. Run the full
tools test suite, template/schema validation and pre-commit checks before
distribution, then verify fresh forward syncs and the resulting fork artifacts.

Local results: the original guard exited 1, the baseline-enabled guard exited 0,
all 224 tools tests passed, and every pre-commit hook passed (including template
and registry-schema validation). Provider v4.3.4 had already passed its release
pipeline's lint, type and test gate; this change does not alter that release.
