# Nonresumable exact-entry save-state correction — July 28, 2026

## Accepted conclusion

The apparent first RNG/virtual-IRQ divergence at retained arcade tick 7563 was not a
production-ROM scheduling failure. It was produced by reloading a Nexen save state
whose own capture metadata already classified it as a nested exact-entry forensic
state:

- state:
  `build/playtest-investigation-20260725/snes-rng-bisect-from-t07560-to07570-dense-2235a21-v1/states/snes-tick-07561.mss`;
- SHA-256:
  `1926eafecc266c5ce07876a3f6044768ae8a3af7239700667d3bcf9e448b3758`;
- `boundary_kind=sa1_exact_entry_nested_forensic`;
- `entry_exact_bundle=true`;
- `nested_sa1_entry_nonresumable=true`;
- `resumable_checkpoint=false`.

This is classified as **stale/nonresumable save-state data and harness misuse**, not
interpreter, native/HLE, renderer, or demonstrated production timing behavior.

No change to the current `$2328` paced virtual-IRQ reload is justified by this
evidence. The exploratory `$2ABF`, `$2F60`, `$33F3`, `$46AB`, `$B03D`, and `$7000`
reload/migration outcomes remain retained as rejected diagnostics only.

## What reproduced the false symptom

Loading the state above and asking for two future update-entry stops produced the
same long gap in both configurations:

- native-on:
  `rng-two-entry-single-stop-native-on-2235a21-v1`;
- native-off:
  `rng-two-entry-single-stop-native-off-2235a21-v1`.

Both used production ROM SHA-256
`2235a21916fbb27a9046bd46984993135280cc44b77ea2136aad0e38ef316b9e`.
The native-on arm reached video frame 23,844 and the native-off arm frame 23,847
while the raw SNES tick remained 7,560 and RNG remained `$3B50`. Because the common
input state was already declared nonresumable, this agreement says only that both
routes inherited the same invalid serialized debugger context.

## Controls that rejected a ROM-cadence conclusion

Allowing execution from the same forensic state to progress by real raw-tick
boundaries with nonpausing hooks recorded the expected ordering in both native-on and
native-off diagnostics:

```text
RNG $3B50
idle $0818
IRQ reload
take IRQ
game-update entry $003A92
RNG $4D03
idle $0818
IRQ reload
take IRQ
game-update entry $003A92
```

Those retained directories are:

- `rng-t7561-heavy-irq-order-native-on-reload2328-2235a21-v1`;
- `rng-t7561-heavy-irq-order-native-off-reload2328-2235a21-v1`.

The exact-stop counter itself also matched the older scoped-breakpoint mechanism for
one and two occurrences in
`exact-stop-equivalence-heavy-t7561-2235a21-v1` (`2/2`, green). That is debugger
control evidence only—the source state remains nonresumable—but it rules out a simple
off-by-one difference between the two stop implementations once they are operating
on an established live entry.

The authenticated campaign continuation from a real safe checkpoint remained
arcade-player exact through tick 9,657. Its pre-failure state is:

- `resume-safe3000-to9662-prefailure-2235a21-v1/states/safe-checkpoint-09657.mss`;
- SHA-256:
  `159ec37dc3adb17ae6e465db185441cba9b59db2a3e2fecc2cd7f5238d93fb88`;
- `boundary_kind=post_entry_safe_snes_boundary`;
- `resumable_checkpoint=true`;
- three repeated save files are byte-identical.

The first accepted gameplay-visible mismatch therefore remains the missed player
damage at arcade tick 9,658 / comparison tick 9,661. Investigation must start from
that safe checkpoint, never from an exact-entry snapshot retained during the failing
update.

## Regression

`tools/capture_snes_movie_ticks.py` now requires an authenticated fresh-campaign
lineage log and a `post_entry_safe_snes_boundary` state by default. Explicitly nested
or unverified states require `--allow-forensic-nonresumable-state`; outputs under that
override state that they are not production-behavior evidence.

`python3 tools/val_capture_state_resumability.py` covers safe acceptance, default
nested-state rejection, explicit forensic classification, and default rejection of a
state with no lineage.

This report changes no claim about current-ROM performance. MAME instruction/cycle
traces around real mid-update IRQs remain useful oracle evidence, but they do not
establish that the SNES reload is wrong.
