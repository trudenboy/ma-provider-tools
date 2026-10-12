# Yandex Music upstream guard baseline, 2026-10-12

The Yandex Music entry in `providers.yml` acknowledges upstream commit
`406771ec9138f32954e347f8d4b2fec9ecf51005`. This replaces the previously
reviewed `d22d28c087ded4289c67c8121c7697f02d9f6e62` baseline, while leaving
the upstream-ahead guard enabled. KION's baseline is unchanged.

The provider source and test trees at this commit match those at the inspected
upstream dev head `75a7e4859429bfc514640b2c9b4b2fc902d530a1`:

| Path | Tree SHA |
| --- | --- |
| `music_assistant/providers/yandex_music` | `7f5f6631d68f08537e4b432d07fa0e525dca1dbb` |
| `tests/providers/yandex_music` | `b1643aac3761f25f40ffe2df44bf98e08fe0ff66` |

## Reviewed differences

The previous baseline still blocks the released provider v3.8.24 after
upstream lint changes, despite successful acknowledged syncs documented in
[provider issue #339](https://github.com/trudenboy/ma-provider-yandex-music/issues/339).
The guard identifies two residual paths:

- `api_client.py`: upstream added `S311` annotations to request jitter. Those
  annotations are already present in the provider after reverse-sync #6887.
- `provider.py`: upstream added the same jitter annotation, complexity
  annotations to the old monolithic Browse method (#6890), and initialized
  `load_more_modes` before dispatch (#6876). The jitter annotation is present;
  the old dispatch method is superseded by the Browse router. Its My Wave mode
  handler initializes the pagination flag for both accepted path shapes.

The guard automatically recognizes older released snapshots and already-ported
edits for the other differing paths. The latest upstream source edit (#6914)
and test edit (#6905) are also already ported to provider dev.

## Validation and safety boundary

Run `scripts/check_upstream_ahead.py` against upstream head
`75a7e4859429bfc514640b2c9b4b2fc902d530a1`, using domain `yandex_music`,
provider path `provider/`, and the provider checkout:

- Previous acknowledged baseline: exits 1 and flags only `api_client.py` and
  `provider.py`.
- Proposed acknowledged baseline: exits 0; both residual upstream blobs match
  the reviewed immutable commit. No global acknowledgment switch is enabled.

Validation used provider commit `b48ee45` (v3.8.24 plus the terminal initial
radio-session fix). That fix affects only the provider's newer session API,
not the reviewed upstream jitter or legacy Browse changes.

Future upstream edits change blob hashes and are still checked. Merge this
registry change through the normal hub PR workflow; distribution then updates
the generated provider workflow inputs. Do not hand-edit rendered wrappers.
