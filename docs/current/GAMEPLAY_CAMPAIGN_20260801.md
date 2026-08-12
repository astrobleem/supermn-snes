# Current gameplay validation campaign — 2026-08-01

This report originally recorded the `f369e327…` rebuilt ROM, then the
`9dcc…` campaign. The active ordinary image is now the isolated terminal-CCR
repair `a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60`.
It is evidence, not a playable-release claim.

## Superseding isolated a976 CCR repair

The active ROM is a 66-byte, hash-guarded patch of preserved `5c7e…`, not a
normal dirty-source rebuild. It publishes the MC68000 `TST.B` NZVC result,
without changing X, on the inactive `$02429C` root-record and `$0259CA`
scan-record native exits before their terminating DBRA. Exact original MAME
0.287/native-off/native-on controlled comparisons are green 9/9 at
`build/validate-2429c-distinct-arm-isolated-a976-pinned-v1.jsonl`.

Its organic fresh power-on MAME-controller replay is green through tick 10,000
at `build/fresh-candidate-2429c-tstb-ccr-isolated-a976-to10000-v1`: 2,062
green comparisons, five matched deaths, no halt/divergence/state load/ROM or
game-state mutation, and observed walking, Button 1 punch/charge, Button 2
kick, Up flight, crate pickup/carry/throw, hurt, and respawn. Its independent
fresh one-credit HUD/art replay is green at
`build/validate-fresh-one-credit-prompt-isolated-a976-v1/summary.json` for the
transparent CREDIT underlay, intact right artwork, clean lower-right region,
one credit, live task mask, and no halt. It is not an organic boss, Stage-3
transition/timing/rate, or full-playthrough claim. The independent legacy-Mesen
cold-boot prompt run is also green at
`build/validate-fresh-one-credit-prompt-isolated-a976-mesen211-v1/summary.json`.

Focused combat is now re-run on `a976…`: the ordinary-enemy three-way matrix
is green 4/4 at `build/validate-gameplay-damage-current-a976-v1` (Button 1
punch 1, Button 2 kick 2, contact 4, charged projectile 4), and the boss
matrix is green 118/118 at `build/validate-boss-health-current-a976-v1.json`.
The retained arcade boss sequences are Stage 1 40 HP/13 hits, Stage 2 40/37,
and Stage 3 20/6. These are interrupt-masked handler differentials, not
organic continuous boss or campaign-completion proof.

The active organic crate carry/throw branch is green at
`build/validate-organic-crate-current-a976-v1/summary.json`. It resumes an
authenticated same-hash fresh-boot tick-3,000 state and compares all 87 exact
controller entries in original MAME, native-off, and native-on. The 17 carried
crate/enemy contacts at ticks 3,253--3,269 write no enemy health; only a
Button 1 throw produces the two original one-point health transitions at
ticks 3,274 and 3,283. The separate Up+Right flight control is independently
green at `build/validate-organic-crate-flight-current-a976-v1/summary.json`:
it switches to flight at tick 3,253, has material ascent and true carried
crate/enemy overlap, and produces zero health transitions in all three
configurations. This is an organic checkpoint-branch result, not a campaign
completion or performance result.

The same fresh native-on root reaches tick 14,746 without a controller-player
mismatch, retaining an authenticated tick-14,743 safe state and tick-14,745
boundary state. The exact comparison of that safe state with pinned original
MAME 0.287 and the two SNES configurations is nevertheless red at tick 14,746
in `build/validate-stage3-irq-order-current-a976-v1.json`: MAME task 15 saves
`$0259B0/$0242BE`, SR `$2400`; both native-off and native-on save
`$02429C/$00044E`, SR `$2404`. This is a current hardware-boundary/virtual-IRQ
timing result, not a stale state or native-only result. The matching
current-hash checkpoint-local neutral measurement is 2,471,287.70 SA-1
cycles/tick native-on and 11,320,496.0 all-native-off
(`build/measure-stage3-current-a976-safe14743-v1/summary.json`), both above
the 358K budget. These are not FPS, Stage-3 completion, or full-playthrough
claims.

The one-tick native-entry trace used to scope the Stage-3 timing root is also
now checked against the active ROM pack, rather than assuming a normal source
rebuild: `build/validate-active-native-entry-alignment-current-a976-safe14743-v2.json`
has 236 exact source-byte entry hits and four hits at two documented
production counter strips (240 total). In particular, the `escbank9` payload
starts at `$9F:A100` / file `$2FA100`; treating it as `$9F:8000` was an
address-mapping diagnostic error, not a gameplay discrepancy. This narrow
provenance check does not prove all source/binary identity or relax the Stage-3
timing blocker.

The active ROM also has a same-hash one-tick Stage-3 fetch-boundary hotspot
record at `build/profile-stage3-tick-current-a976-safe14743-v1/profile.json`:
1,936,861 SA-1 cycles, 11 video frames, and 413 fetches. `$0242BE` is its
largest single attribution at 101,454 cycles (5.24%) and the top 20 comprise
40.35%. Because the profiler pauses at every fetch, this is only hotspot
selection evidence; it rules out a one-routine explanation but is neither a
rate/FPS claim nor a timing or gameplay repair.

Its qualified logical-region reduction at
`build/analyze-stage3-current-a976-hot-regions-safe14743-v1.json` identifies
the `$027B` record-emitter family at 32.52% and `$02E4-$02E5` draw
dispatch/call setup at 18.71% of the perturbed tick. These are optimization
selection lower bounds, not independent native-span costs or a claimed rate
fix; the task-15 clock defect remains separately open.

The selected `$027B` family then revealed an active native/HLE route gap. The
same safe-checkpoint trace enters native parent `$027952` 12 times but enters
neither `$027B44` nor `$027B7C`, despite 60 original-MAME executions of each
in the retained Stage-3 trace. The bank-$02 sparse dispatcher lacked their
exact cases and fell through to the interpreter. Candidate `387855da…` adds
those two cases and the already-proven guarded `$027AEA` parent edge. Its
same-state full-parent original-MAME/native-off/native-on differential is
green 14/14, its organic trace reaches all three children 12 times each, and
its fresh one-credit HUD/art boot is green. The joined evidence is
`build/validate-stage3-record-emitter-route-coverage-current-a976-v4.json`.
That v4 reduction also retains the next live sparse miss, `$02E524`: it has
60 original-MAME executions but zero active/candidate wrapper entries. The
candidate itself is rejected by an independent fresh power-on controller replay:
at MAME tick 2,958, two ticks after a Button 1 edge, MAME enters action 1 while
candidate SNES remains action 0 at the same position and health
(`build/fresh-campaign-stage3-record-emitter-route-current-a976-to14746-native-on-v1/summary.json`).
The initial harness classification is timing, but source's shared-dispatcher
guard proves the candidate cannot establish Stage-3 provenance from canonical
pointer/stack state. Its unsafe source routes have been removed; the narrow
builder retains `387855da…` only as a reproducible rejected experiment. Its
`tools/test_shared_dispatch_stage_provenance.py` guard keeps those routes out
of the freshly assembled shared dispatcher, while
`tools/test_rejected_shared_dispatch_fresh_failure.py` guards the fresh
pre-input failure evidence at `states/pre-failure-input.mss` (SHA-256
`80799f…`, SA-1 IRAM sidecar `ca40bb…`). Its checkpoint rate is therefore not
a Stage-3 rate or timing acceptance.

The safe follow-up is a parent-local route rather than a shared-dispatch case.
Candidate `0453ef75…` directly bridges only native `$027952` to its guarded
`$027AEA/$027B44/$027B7C` children, preserving the Stage-1 interpreter route.
It is green 14/14 in the bounded original-MAME/native-off/native-on parent
matrix, fires each child 12 times in the safe Stage-3 tick, and clears a fresh
controller replay through tick 3,000 with zero oracle divergences, including
the tick-2,958 Button 1 response. Its red terminal is the requested-coverage
guard, while its Stage-3 rate remains red at 1,782,190.23 cycles/tick. See
`build/validate-stage3-parent-local-record-emitter-current-a976-v1.json`;
Follow-on `91cf499f…` adds the same parent-local bridge for `$02E524`: it is
also 14/14 exact, enters the live wrapper 12 times, and clears fresh tick 3,000
with zero divergences. Its 1,571,650.55-cycle checkpoint rate is still red.
An authenticated continuation from its fresh-lineage safe tick-10,000 state
reaches requested MAME tick 14,746 with zero oracle divergences, 2,744 green
player references, and six deaths at
`build/playback-watcher-20260808/parent-local-draw-91cf-resume10001-to14746-native-on-v3/watcher-report.json`.
It is still `partial-green`: boss-event coverage is zero, and it is a resumed
segment rather than an uninterrupted full campaign. Neither candidate has a
passing rate, timing repair, boss campaign, or playthrough proof.

The authenticated native-on continuation from that fresh tick-14,743 safe
state has now reached tick 15,050 at
`build/continue-stage3-current-a976-safe14743-native-on-v1`. It observes 15
downstream player differences but no halt, invalid task stack, or renderer
stall; this is post-divergence liveness only. The narrow rerun
`build/continue-stage3-current-a976-safe14743-native-on-prefailure-v2`
reproduces the first visible difference at tick 14,841 after a green
tick-14,839 input boundary: MAME is idle with 4 HP at `(52,112)` and SNES is
state 9 with 20 HP at `(68,96)`. It preserves an immutable hash-checked
pre-input state plus SA-1 IRAM sidecar before that response. The snapshot is an
exact-entry forensic state and is intentionally not used as a resumable
checkpoint. This is deterministic downstream evidence for the already-proven
tick-14,746 virtual-IRQ split, not a new combat, renderer, or native-only
classification.

The supplemental fresh gameplay-root-off controller runner has one repaired
prefix, not a completed campaign. The older attempts timed out because they
cleared `$071A/$073A` and then waited for the native `$92:DB82` address that
those gates intentionally bypass. The fresh power-on replacement
`build/fresh-campaign-current-a976-native-off-first-entry-v6` stops at Nexen's
counted rising IRAM `$0040` virtual-PC `$003A92` edge instead. It is
`partial-green`: title/credits/start/spawn reproduce the MAME tick-221 player
state, the deliberately disabled gates are zero, its single tick-222 virtual
edge passes every stop-contract check, and halt remains zero. The fresh
companion `build/fresh-campaign-current-a976-native-off-first-movement-v1`
then reaches tick 1,060: it applies Left at tick 1,054 and original MAME plus
the SNES root-off run have the tick-1,056 X response from 64 to 61. It still
contains no punch,
kick, flight, boss, death, Stage-3, or rate coverage, so it is not a complete
native-off gameplay or all-escapes-disabled claim. The exact native-off half
of the preceding Stage-3 three-way comparison remains valid authenticated
checkpoint evidence.

The same organic current-hash replay retains its live campaign-end screenshot
at `build/fresh-campaign-current-a976-to14746-native-on-v1/screenshots/campaign-end.png`.
It has intact city/background artwork and no visible vertical blue bar. This is
fresh-lineage Nexen visual evidence, unlike the supplied old `stage3.mss`; it
does not establish MAME-aligned pixels or renderer conservation.

The source-built `b758…` image is rejected: it contains 2,749 bytes of drift
over 322 diff runs and its fresh replay reaches only 10 update entries in
2,456 video frames before hardware-boundary/timing failure
(`build/fresh-candidate-2429c-tstb-ccr-b758-to3000-v2/summary.json`). The
following `5c7e…` sections are retained predecessor evidence unless explicitly
re-run on `a976…`; the immediately preceding current Stage-3 IRQ/rate results
are the exception and remain red blockers.

## Superseding 5c7e rebuild update

The rebuild corrects a VTIME diagnostic BW-RAM addressing bug and adds byte
guards for both that diagnostic and the disabled ordinary pack. VTIME remains
off in the normal ROM; the legacy countdown seams are still present in both
bank-$00 mirrors. Fresh one-credit prompt checks on this exact hash are green
in Nexen at
`build/validate-fresh-one-credit-prompt-current-5c7e-nexen-v1/summary.json`
and legacy Mesen at
`build/validate-fresh-one-credit-prompt-current-5c7e-mesen211-v1/summary.json`.
They re-prove the artwork/HUD symptoms from cold boot. The authenticated
current-hash continuation is now green through MAME tick 10,000 at
`build/fresh-campaign-current-5c7e-resume10000-v2`: it retains the real
fresh-power-on lineage, 2,062 green player comparisons, five matched deaths,
zero oracle divergences/halts, and walking, Button 1 punch/charge, Button 2
kick, Up flight, crate pickup/carry/throw, hurt, and death/respawn. This is
bounded Stage-1/2 coverage, not an organic boss fight, Stage-3 transition,
rate result, or full playthrough. The 9dcc focused gameplay, boss, crate, and
Stage-3 reports immediately below remain predecessor evidence pending their
current-hash reruns. One focused rerun is now complete: the current
ordinary-enemy matrix is green 4/4 at
`build/validate-gameplay-damage-current-5c7e-v1`. Exact MAME,
gameplay-native-off, and production-native-on agree for Button 1 punch damage
1, Button 2 kick damage 2, contact damage 4, and charged projectile damage 4,
with bounded register/CCR/X, stack, work-RAM, and health-write comparisons.
It does not promote the separate boss/crate tests or imply a whole-game run.

After the later focused VTIME diagnostics, the preserved active `5c7e…` ROM
was cold-booted again in Nexen. The new
`build/validate-fresh-one-credit-prompt-current-5c7e-esc9-post-v1/summary.json`
uses one real Select edge and is green for all seven title/HUD predicates:
one credit, intact right wedge, transparent CREDIT underlay, no lower-right
garbage, nonzero task mask, and no halt. This is fresh-ROM renderer/HUD proof,
not a campaign or Stage-3 claim.

The required post-focused organic replay has been rerun from a fresh power-on
on the active `5c7e…` ROM. Its bounded first segment,
`build/fresh-campaign-current-5c7e-post-focused-to10000-v1`, is green through
tick 10,000 with 1,031 controller transitions, 2,062 green MAME/SNES player
comparisons, five matched deaths, no state load, no ROM/game-state mutation,
and no halt. It observes action states 0/1/2/3/4/5/7/8/9/10, including punch/
charge, kick, Up flight, crate pickup/carry/throw, hurt, and respawn. It is
bounded action coverage, not a boss, rate, or full-playthrough result.

The independent fresh-power-on extension
`build/fresh-campaign-current-5c7e-post-focused-to14841-v1` is intentionally
red at tick 14,841 after 2,757 green player comparisons and 12 matched deaths:
MAME is action 0, 4 HP, `(52,112)` while production SNES is action 9, 20 HP,
`(68,96)`. It retains atomic forensic `states/failure.mss` (`85664aaa…`) and
does not restore it into the active run. This is fresh-ROM proof that the
downstream symptom is not stale save-state data; it complements, rather than
replaces, the exact MAME/native-off/native-on task-frame regression at tick
14,746. It does not claim a Stage-3 repair, usable rate, or full playthrough.

For deterministic focused reproduction, the authenticated continuation
`build/reproduce-current-5c7e-14841-preinput-v2` resumes only from the
fresh-lineage safe tick-10,000 boundary and arms the tick-14,839 neutral
controller edge. It is red at tick 14,841 with the same player mismatch and
retains `states/pre-failure-input.mss` (`1c4a5cec…`) before the edge, alongside
the post-failure state. This closes the pre-failure-state evidence gap; it is
not substitute fresh-boot, rate, or repair proof.

The current boss rerun is green 118/118 at
`build/validate-boss-health-current-5c7e-v1.json`: original MAME,
gameplay-native-off, and production-native-on agree across every retained
organic initialization and health-write handler case. The exact arcade
sequences are Stage 1: 40 HP / 13 hits; Stage 2: 40 HP / 37 hits; Stage 3: 20
HP / 6 hits. The test masks 68000 interrupts within each bounded handler span,
so it proves correct initialization/damage semantics rather than a continuous
fresh-SNES encounter.

The current organic crate carry/throw controller branch is green at
`build/validate-organic-crate-current-5c7e-v1/summary.json`. It resumes from
the current ROM's authenticated fresh-power-on tick-3,000 safe state, with no
ROM migration, and compares 87 exact MAME/native-off/native-on controller
entries per branch. Carried contact produces zero enemy-health transitions;
after Button 1 throws the crate, all three configurations agree on the two
one-point enemy-health transitions at ticks 3,274 and 3,283. The separate
current-hash Up+Right flight-contact control is also green at
`build/validate-organic-crate-flight-current-5c7e-v1/summary.json`: its
MAME-confirmed carried-crate/enemy overlap and material ascent have zero
enemy-health transitions in original MAME, native-off, and native-on.

The current fresh lineage now continues cleanly through tick 14,743 at
`build/fresh-campaign-current-5c7e-resume14743-v1`, retaining a resumable
post-entry state. From that same state, exact original MAME, gameplay-native-
off, and production-native-on are green at ticks 14,744--14,745 and red at
14,746 in `build/validate-stage3-irq-order-current-5c7e-v1.json`. MAME saves
task 15 at `$0259B0` / `$0242BE`, SR `$2400`; both SNES configurations save
`$02429C` / `$00044E`, SR `$2404`, followed by collision/RNG differences.
The exact native-on delivery reproduction
`build/capture-stage3-irq-delivery-current-5c7e-v3/summary.json` reloads the
same state in a fresh Nexen process, verifies the recorded full public state
and SA-1 IRAM sidecar before controller restoration, then remains red at the
same physical point: no `$025110` mid-call yield and IRQ delivery at `$0818`
with task 15 still `$02429C`/`$00044E`. It corroborates the three-way result,
but is not fresh-boot, native-off, rate, or repair evidence.
The companion authenticated current-ROM call-site trace at
`build/trace-stage3-ac94-callers-current-5c7e-v1/summary.json` observes all
82 bank-$94 legacy-charge sites. The failing update alone adds 12 visits each
to `$94:D548/$94:D567/$94:D586`, the three 3/2/5-instruction blocks of the
`$02E40E` address leaf. This identifies a variable-work trigger for the late
IRQ, but native-off fails at the same frame, so it is not a one-leaf repair or
a complete cause classification. The associated regression
`build/validate-stage3-ac94-variable-work-current-5c7e-v1.json` is green only
because it preserves that failure trigger.
The corresponding original-MAME reduction is green at
`build/analyze-stage3-2e40e-cycles-current-5c7e-v1.json`: the leaf costs 80
cycles below D0 byte 7 and 94 at/above it; tick 14,746 has seven and fourteen
of those paths. An authenticated native countdown trace now directly observes
the same red-tick calls subtracting 3/2/5 legacy instruction units from `$AC`;
`build/validate-stage3-ac94-countdown-current-5c7e-v1.json` preserves that
mixed-unit observation. This is timing-ledger input only, not a leaf fix.
The same current lineage then reproduces the false respawn at tick 14,841 in
`build/fresh-campaign-current-5c7e-resume14841-v1`; its tick-14,839 retained
boundary is the pre-failure state. This is current evidence of the timing root,
not a repair, fresh Stage-3 completion, or performance result.

A separate dirty-source terminal-CCR candidate,
`build/interp-2429c-tstb-ccr-candidate-b758.sfc` (`b7584c6f…`), repairs two
native `TST.B` edges in the `$02429C/$0259CA` path that previously left the
interpreter CCR image stale after a terminating DBRA. Exact MAME 0.287,
native-off, and native-on controlled inputs are green 9/9 at
`build/validate-2429c-distinct-arm-candidate-b758-pinned-v2.jsonl`, and all
three retained organic entries are green 9/9 at
`build/validate-2429c-organic3-candidate-b758-pinned-v1.jsonl`. Its fresh
one-credit HUD/art control is green too. These are masked-IRQ function and
fresh-prompt checks, respectively; they do not repair the all-mode tick-14,746
clock divergence, establish a usable Stage-3 rate, or replace active `5c7e…`.

The follow-on checkpoint continuation now reaches tick 15,000 at
`build/campaign-stage3-current-5c7e-continue15000-v2/summary.json`. It starts
from the authenticated tick-14,743 safe state, retains the tick-14,839
pre-input state, and records the same first false respawn at tick 14,841.
With explicit oracle-divergence continuation enabled, its suffix records 15
player discrepancies (7 at input boundaries and 8 at input-response
boundaries) and completes with halt zero, valid task stacks, and live renderer
state. The suffix is organic-path coverage only; it is not exact-state proof,
fresh-boot proof, rate evidence, a boss result, a Stage-3 completion, or a
full playthrough. The corrected harness behavior is covered by
`tools/test_campaign_oracle_continuation.py`; the resume compatibility exception
is limited to the named predecessor runner hash and does not relax any ROM,
MAME, emulator, bridge, symbol, or checkpoint identity check.
The next chained continuation,
`build/campaign-stage3-current-5c7e-continue15250-v1/summary.json`, runs from
tick 15,001 through 15,250. It adds 14 green player comparisons and no new
discrepancy, halt, invalid task stack, or renderer failure. Like its parent,
it is post-divergence liveness coverage only, not recovery or a completion
claim.

The VTIME player-ledger extension is diagnostic-only and uses a separate
`68c9bccc…` copied ROM. It has green fresh liveness, forced first-block
deadline, and forced exit-gateway deadline tests, while the six bounded real
`$013282` fixtures never reached their OJMP handoff. That is an explicit
coverage limitation; no player-ledger timing, Stage-3 rate, or organic
gameplay result transfers to the active `5c7e…` production image.

The required longer boot control rejects that VTIME diagnostic in both SNES
gate configurations before gameplay. Its fresh native-off and native-on
controller replays are red at
`build/validate-vtime-esc9-nativeoff-fresh3000-v1/summary.json` and
`build/validate-vtime-esc9-nativeon-fresh3000-v1/summary.json`: after 5,248
real frames and eight real Select edges, each has zero credits and the same
boot-screen pixels. A fresh exact-MAME-0.287 boot-aware one-credit control
does enter gameplay (reported frame 1,952; state under
`build/mame-vtime-boot-oracle-v1`). The VTIME pair never reaches a gameplay PC
for a valid D/A/CCR/stack differential. A separate long timer probe proves
that its timer is alive but unusably slow—53 observed virtual deadlines over
5,248 real frames, with PC remaining `$003F7C→$003FEE` in the boot RAM test.
This is a hardware-rate/common-clock rejection, not evidence of a production
ROM failure or a safe partial `$AC` repair.

Exact-Nexen stop-by-stop attribution from the tick-14,743 state is retained at
`build/profile-stage3-tick-current-5c7e-safe14743-v1/profile.json`: a single
update consumed 1,938,567 SA-1 cycles, 11 video frames, and 310 genuine
interpreter fetches. The `$02429C` native fusion and `$025110` collision guard
fired. This is a perturbed checkpoint hotspot trace, not uninterrupted fps or
fresh-boot rate proof, but it demonstrates that the 358K cycles/tick target is
substantially missed.

The trace also exposed one real missed nested route: native `$027952` called
the already-generated guarded `$027AEA` child through the generic dispatcher,
which intentionally cannot establish Stage-3 provenance and therefore
interpreted it. The retained byte-minimal candidate
`build/interp-stage3-27952-direct-27aea-current-5c7e-v1.sfc`
(`23268b5d…`) changes only that three-byte JML address operand to `$9F:C000`; it is not
the active ROM. Exact MAME 0.287, native-off, and native-on parent-body
comparisons are green for all 12 retained states at
`build/stage3-27952-direct-27aea-current-5c7e-isolated-v2.jsonl`, including
D/A, CCR/X, stack/return, mapped work RAM, upper backing, and AC. Native-on
uses a declared direct-parent semantic entry, while a separate same-hash
exact-Nexen neutral-input route pair retains zero child hits with gates off
and 36 with gates on at
`build/stage3-27952-direct-27aea-current-5c7e-route-v2` and
`build/stage3-27952-direct-27aea-current-5c7e-route-on-v1`. The generator and
packed-byte guard is `tools/test_stage3_27952_child_bridge.py`. This is a
bounded local candidate only—not a rate, IRQ-order recovery, or a
Stage-3/full-playthrough result—and cannot displace the common-clock blocker.
Its later fresh-power-on native-on extension through MAME tick 3,000 is at
`build/fresh-candidate-27952-direct-27aea-to3000-v1`: title, credit, start,
and gameplay origin are retained; all 168 player comparisons and the one
death/respawn pair are green with no halt or oracle divergence. The overall
result is red only because that shortened segment lacks action states
3/4/5/7/10. It remains a pre-Stage-3 candidate sanity replay, not a promotion
or full coverage result.

The bridge was subsequently rebased byte-minimally onto active `a976…` as
`build/interp-stage3-27952-direct-27aea-current-a976-v1.sfc` (`43ee45ee…`),
with the JML's three-byte destination and the SNES checksum as its only ROM
differences. Its 12 exact MAME/native-off/native-on parent cases plus two
dispatcher route probes are green at
`build/validate-stage3-27952-direct-27aea-current-a976-isolated-v1.jsonl`.
The required post-focused fresh-boot replay is also green through MAME tick
10,000 at `build/fresh-candidate-27952-direct-27aea-current-a976-to10000-v1`:
2,062 player and ten death/respawn comparisons are green; title, credits,
start, punch, kick, Up-flight, crate pickup/carry/throw, hurt, and respawn all
occur with zero divergence or halt. The candidate's Stage-3 safe-state liveness
probe is green but its 2,375,601.72 native-on cycles/tick still misses 358K;
the different command-wall-time spans from the active baseline mean it makes
no reliable cross-ROM speed claim. It is retained, not promoted, and cannot
clear the virtual-IRQ timing blocker. The distinct fresh one-credit gate is
green at `build/validate-fresh-one-credit-prompt-stage3-27952-current-a976-v1/summary.json`,
including the original reported artwork wedge, transparent CREDIT, and
lower-right status predicates.

The same candidate has a limited but real checkpoint-only native-on speedup.
In separate no-hook safe-Nexen sessions from the same tick-14,743 state, with
neutral input over the retained 90-frame window, active `5c7e…` completes three
ticks at 3,468,814 SA-1 cycles/tick
(`build/measure-stage3-current-5c7e-safe14743-onechunk-nohooks-v5/summary.json`),
whereas the candidate completes four at 2,669,361.75 cycles/tick
(`build/measure-stage3-27952-direct-27aea-current-5c7e-safe14743-onechunk-nohooks-v2/summary.json`).
That 23.0% reduction remains 7.46× the 358K target. The measurement harness
now identifies the safe Nexen executable accurately; it retains no hooks,
state hashes, and neutral MCP input, but cannot compare end RAM over unequal
tick counts. It is not fps, fresh-boot proof, an IRQ-order recovery, or a
promotion result.

The campaign’s player-native route coverage has also been corrected. The six
Stage-3 player leaves are reached by the BSR gateway; a generic table-dispatch
fixture had previously tried `$00:D1B3`, which is intentionally not their
production route. That harness now rejects these targets. The genuine
pre-BSR MAME/native-off/native-on checks are green on `5c7e…`:
`build/validate-stage3-13282-bsr-current-5c7e-v3.json` has six `$013282`
cases and its `$9F:E000` route probe;
`build/validate-stage3-13314-bsr-current-5c7e-v2.json` and
`build/validate-stage3-1337e-bsr-current-5c7e-v2.json` each cover one
retained case and their `$9F:D800`/`$9F:BA00` routes; and
`build/validate-stage3-player-bsr-current-5c7e-v2.json` covers 18 retained
`$0133EA`/`$013468`/`$013538` cases and all three native routes. The aggregate
is 26 semantic comparisons plus six route probes, all green for D/A, CCR/X,
stack, mapped work RAM, upper backing, and AC. It corrects the validation
method only; it does not resolve the tick-14,746 hardware-boundary timing
failure or prove a Stage-3 run.

The `$02E42C` selector required a second call-site correction. Its entry
fixtures come from two real PC-relative JSRs, `$0278E2→$0278E6` and
`$02F2DA→$02F2DE`; the latter has a different A0 callback and cannot be
replayed through the former. The call validator now selects the call site from
the retained stacked return. Exact MAME 0.287, native-off, and native-on are
green for all six states and the natural `$9F:A140` route probe at
`build/validate-stage3-2e42c-real-jsrpc-current-5c7e-v4.json`, including
D/A, CCR/X, stack/return, mapped work, upper backing, and AC. This is bounded
handler-route evidence, not a fresh Stage-3 traversal, virtual-IRQ repair,
or usable-rate result.

## Superseding 9dcc campaign update

The current fresh one-credit title/HUD regression is green at
`build/validate-fresh-one-credit-prompt-current-9dcc-nexen-v2/summary.json`: the
right artwork gap is absent, the CREDIT label preserves its art underlay, and
the lower-right status garbage is absent. It is a fresh boot, not a checkpoint.
The independent legacy-Mesen fresh boot is also green at
`build/validate-fresh-one-credit-prompt-current-9dcc-mesen211-v5/summary.json`.
Its 256x224 native screenshot has the same visual predicates green; the
emulator-specific height is explicit in the harness rather than treated as a
renderer mismatch.

`build/validate-gameplay-damage-current-9dcc-v1` is green 4/4 in exact MAME,
native-off, and native-on: Button 1 punch damage 1, Button 2 kick damage 2,
contact damage 4, and charged projectile damage 4. The current ordinary-ROM
boss campaign at `build/validate-boss-health-current-9dcc-v3.json` is green
118/118 using the reversible terminal trap on `9dcc…`: Stage 1 is 40/13,
Stage 2 40/37, and Stage 3 20/6. Both are bounded routine proofs, not
continuous boss fights.

The initial crate branch proves normal held contact versus a legitimate throw
at `build/validate-organic-crate-current-9dcc-v1/summary.json`. The separate
flight route at `build/validate-organic-crate-flight-current-9dcc-v3/summary.json`
deliberately reaches the original 17-boundary carried-crate/enemy overlap,
switches to Up+Right at the host controller boundary, and rises 112 pixels.
MAME, native-off, and native-on all retain exact player, object/collision,
register/CCR/X, stack/return, scheduler, and virtual-IRQ results with no enemy
health write. The first route attempt is retained red in `...-v2`: both SNES
modes applied the switch one entry early. Its saved pre-failure states
deterministically classified that as controller-input timing in the validator,
not gameplay code; `...-v3` delays the Nexen host edge one entry and is green.

The fresh campaign through tick 3,000
(`build/fresh-campaign-current-9dcc-safe3000-v1`) is no-halt/no-player-
oracle-mismatch proof but ends red for incomplete action coverage, and has no
boss or Stage 3. The stale supplied Stage-3 checkpoint and its slow checkpoint
rate remain unpromoted: no current fresh Stage-3 traversal, usable-rate proof,
or full playthrough exists.

The authenticated continuation through tick 10,000 is green at
`build/fresh-campaign-current-9dcc-coverfix-resume10000-v1`: 1,031 real
controller transitions, five matched deaths, no player-oracle divergence, and
no SA-1 halt. It includes walking, Button 1 punch/charge, Button 2 kick, Up
flight, crate pickup/carry/throw, hurt, death/respawn, and action states
0/1/2/3/4/5/7/8/9/10. This still reaches no organic boss battle or Stage-3
transition and is not a complete playthrough.

The continued campaign is red at MAME tick 14,841 in
`build/fresh-campaign-current-9dcc-coverfix-resume18000-v1`. The deterministic
pre-input reproduction state is
`build/reproduce-fresh-14841-current-9dcc-v1/states/pre-failure-input.mss`
(SHA-256 `7c12101135dacd2bb0467a255f1717d2ada53cd60dd0034bf07b7e223ad63e77`).
At exact tick 14,839 MAME has `$F03A02=$0000`; gameplay-native-off and
production-native-on both have `$80F0`. At tick 14,840 MAME remains action 0,
health 4, x=52, y=112; both SNES configurations have action 9, health 20,
x=68, y=96. `build/validate-stage3-false-hit-chain-current-9dcc-v1.json`
retains the intentionally-red focused regression. The `$025110`
interpreter-fallback control reproduces the marker from the same authenticated
state, excluding that native escape as the root. The fault is downstream of
the earlier tick-14,746 task-15 virtual-IRQ ordering divergence shared by both
SNES configurations: classify it as hardware-boundary/timing, not an
interpreter-only, native/HLE-only, renderer, or stale-save-state discrepancy.
No source timing fix has been accepted; no fresh Stage-3 completion or
full-playthrough claim is made.

The current-ROM task-frame regression is
`build/validate-stage3-irq-order-current-9dcc-v2.json`. It compares exact
original-code MAME, gameplay-native-off, and production-native-on from the
same authenticated checkpoint. Ticks 14,744--14,745 match in the selected
player, enemy, boss, RNG, collision, and task-15 regions. At 14,746 MAME saves
task 15 at `$0259B0`/`$0242BE` with SR `$2400`; both SNES modes have the same
`$02429C`/`$00044E` frame with SR `$2404`, followed by collision-table and RNG
differences. This is a focused timing regression, not an organic Stage-3
completion or performance measurement.

All following `f369…` sections are retained historical provenance and do not
override this update.

## Rejected pool-scanner acceleration — not production evidence

The attempted table/rts clones of the `$02498C` and `$0249C2` object-pool
scanners, with a sparse `$9D:B600` dispatcher, are rejected. At the retained
fresh-lineage tick-14,743 entry fixtures,
`build/validate-pool-scanner-table-1512bc19-v10/results.jsonl` reports
MAME/native-off green for both scanners and native-on red for both: the clone
lost D0/D1/D6 plus A0/A1 residue and changed 2–4 mapped work-RAM bytes. The
same result remained after correcting an unrelated Poppy short-branch-over-JML
layout hazard. The generated clones and their xlat route are absent from the
subsequent `adac11f4…` diagnostic rebuild (their `$9D:B400/$B600/$B940` islands
are zero). Its fresh one-credit check
`build/validate-fresh-prompt-scanner-revert-adac-v1/summary.json` is green, so
the right artwork, transparent CREDIT label, and clean lower-right prompt
survive the withdrawal. Its bounded Stage 3 hot-handler and scroll-task
differentials are also green (32/32 and 9/9) at
`build/validate-stage3-hot-scanner-revert-adac-v1` and
`build/validate-stage3-scroll-scanner-revert-adac-v1`. `adac…` is not the
`f369…` candidate and none of the following end-to-end gameplay or performance
evidence transfers to it.

The same `adac…` diagnostic rebuild subsequently passed its bounded
MAME/native-off/native-on ordinary-enemy attack differential 4/4 at
`build/validate-gameplay-damage-scanner-revert-adac-v1`: punch, Button 2 kick,
contact, and charged projectile match health writes, D/A registers, CCR/X,
stack, and mapped work RAM. Its held/thrown crate differential is green 12/12 at
`build/validate-crate-damage-threeway-scanner-revert-adac-v1/summary.json`:
held `$2000` produces zero enemy-health writes and thrown `$2001` one. These are
bounded roots, not organic carried-flight or IRQ-cadence evidence. The current
production ROM cannot be used by the boss validator's PC-ring terminal stop, so
the attempted current-build boss run has no result. A short exact-Mesen checkpoint
probe (`build/measure-stage3-scanner-revert-adac-v3-short/summary.json`) is red:
native-on completed only three ticks at 804,179 cycles/tick and native-off no
tick. It is explicitly too short for a sustained performance claim.

## Green focused differentials

- `build/validate-fresh-prompt-current-f369-v1/summary.json` is green on the
  current hash from a power-on run with one real Select edge: the right artwork
  wedge has no black gap, the credit text preserves its artwork underlay, lower
  right status garbage is absent, and the fresh credit count is one. This is a
  fresh-boot renderer check, not a whole-game graphics pass.
- Independent rerun `build/validate-fresh-prompt-current-f369-v2/summary.json`
  is also green on the same hash from a new power-on with one real Select edge.
  It retains the screenshot and state, and again finds no right-side black gap,
  no lower-right status garbage, and no credit-label overwrite of the artwork.
- The ordinary dirty rebuild `8b9adc92…` also has a fresh power-on, one-credit
  title/HUD result at
  `build/validate-fresh-one-credit-prompt-vtime-default-8b9a-v1/summary.json`:
  all seven checks are green, including the artwork wedge, credit underlay, and
  lower-right area. This validates removal of a disabled-VTIME pack overhead;
  it does not replace the accepted `f369…` campaign hash or prove gameplay.
- That same `8b9adc92…` line subsequently fails a fresh controller replay at
  MAME tick 2,958: the Button 1 response is delayed after a 532,224,800-cycle
  108-update span. The retained state is forensic-only. The current ordinary
  `3d0cc84d…` rebuild removes the unsafe shared-dispatch Stage-3 routes and
  restores the local IRQ reload. Its fresh native-on replay through tick 3,000
  has 168 green player comparisons, zero oracle mismatches, and a green Button
  1 response at tick 2,958. Its final red result is only the deliberate
  incomplete-controller-coverage check. The native-off fresh run reaches the
  same fresh origin then exceeds the old exact-entry watchdog before one
  interpreter-only update; this is an open interpreter-performance/harness
  blocker, not native-off proof.
- The same ordinary `3d0cc84d…` build also passes a new fresh power-on,
  one-credit prompt check at
  `build/validate-fresh-one-credit-prompt-current-3d0c-v1/summary.json`.
  The right artwork wedge, transparent credit underlay, and lower-right area
  are all green. This proves the reported prompt repair survives this source
  change, not any stored gameplay checkpoint.
- The actual ordinary `3d0cc84d…` ROM now has a full bounded boss-health
  matrix at `build/validate-boss-health-current-3d0c-v3`: MAME, native-off,
  and native-on are green for all 118 initialization/damage cases. The
  reversible terminal trap avoids relying on the PC-ring diagnostic ROM.
  Arcade values are Stage 1 40 health/13 hits, Stage 2 40/37, Stage 3 20/6.
  This is exact routine evidence, not an organic boss fight.
- Current crate roots are green with retained pre-execution states:
  `build/validate-25110-current-3d0c-held-thrown-v1` is 4/4 for carried
  `$2000` and thrown `$2001` collision emission, and
  `build/validate-1e7c0-current-3d0c-held-thrown-v2` is 6/6 for response
  consumption. The latter's all-gates-off row truly begins at `inext`.
  MAME records no health write for held contact and one only after a thrown
  response; both SNES post-states match. This remains a bounded chain, not
  an organic carried-flight test.
- The supplied Stage-3 checkpoint remains a diagnostic reproducer, not a
  fresh-ROM result. `build/validate-stage3-scroll-current-3d0c-v1` observes
  the 51-column blue bar at initial `BG1HOFS=288`; both native modes clear it
  only after the input span. The current short rate probe is red at 2,299,747
  SA-1 cycles/tick over two native-on ticks, so Stage 3 speed remains open.
- `build/validation-crate-current-f369-v2.jsonl/summary.json` is green 12/12 on the current hash
  across exact MAME 0.287, native-off, and native-on. A carried crate emits `$2000`
  and records contact with zero health writes; a thrown crate emits `$2001` and the
  consumer performs exactly one health write. Register/CCR/mask/stack/work-RAM
  comparisons are green. The report explicitly does not claim organic IRQ cadence.
- The independently rerun artifacts use the same current hash:
  `build/validate-gameplay-damage-current-f369-v2` is green 4/4, and
  `build/validate-crate-damage-threeway-current-f369-v2/summary.json` is green
  12/12. The latter explicitly records zero health writes for carried `$2000`
  contact and one health write only after the thrown `$2001` response is
  consumed. These fixture paths use the exact recovered MAME 0.287 plus both
  Nexen configurations; they are not an organic carried-flight proof.
- `build/validation-gameplay-damage-current-f369-v2` is green 4/4 in exact MAME
  0.287, native-off, and native-on for punch (damage 1), Button 2 kick (damage 2),
  body/contact (damage 4), and charged projectile (damage 4). Each case compares
  D/A registers, CCR/X, exact stack, mapped work RAM, health writes, and upper
  backing conservation. The first concurrent attempt is retained as a harness
  failure and is not evidence.
- `build/validation-boss-current-f369-v1.json` is green 118/118 in exact MAME
  0.287, native-off, and production-on. Stage 1 initializes at 40 health and has
  13 recorded hits; Stage 2 initializes at 40 and has 37; Stage 3 initializes at
  20 and has 6, with the arcade damage sequences. This is bounded initialization/
  damage evidence, not a continuous organic boss fight.
- `build/validation-stage3-scroll-current-f369-v1` is green 9/9 and
  `build/validation-stage3-hot-current-f369-v1` is green 32/32 on the current hash
  across exact MAME 0.287, native-off, and native-on. They compare D/A registers,
  CCR/X, stack, mapped work RAM, upper-backing conservation, halt state, and real
  native route probes. These are bounded checkpoint handler tests, not fresh organic
  Stage 3 entry or a complete playthrough. The extracted exact oracle is
  `/tmp/mame-4339-recovery/root/mame` (snap revision 4339, SHA-256
  `297843036f728695878300f3bd9949122907cd83bfd6d501875e9a49cd950c6f`).
- The paced `$025110` collision differential first went red at the fresh retained MAME tick-10155 boundary only in native-on: MAME and native-off wrote outer response bytes `$FE1A/$009E`, while the charged generated native path left them zero. The cause is the paced native/HLE stage-2 implementation, not stale state or the interpreter. The production fix is in `src/escbank7.pasm`: the compact scan now runs in the paced path, and any noncanonical shape resumes the untouched 68K interpreter at `$025330` instead of using the lossy generated fallback. `build/validate-25110-current-f369-organic-paced-v1.jsonl` is green for the organic fixture (MAME/native-off/native-on, registers/CCR/mask/work RAM); `build/validate-25110-current-f369-guard-paced-v2.jsonl` is green 80/80 across active-count, overlap, signed-edge, X, and stage-5 guard shapes. This is a focused collision/return regression, not a complete IRQ-cadence or FPS result.
- The packed-source `$0026FA` writeback guard is green at
  `build/validation-26fa-writeback-current-f369-v1`; its current-ROM dynamic
  three-way capture at the retained shake window is still pending.

The final cold-boot-safe ROM retains the byte-exact `$E9:BB00` scroll helper used
by the green fresh-prompt run. An experimental helper that changed the regular
Stage-3 high-byte publication was rejected: it made the fresh boot stop before
the title prompt. The reported Stage-3 blue strip therefore remains open rather
than being declared fixed from a stale checkpoint.

A later isolated source candidate addresses the distinct restore boundary
without changing any MC68000 or producer scroll value: after an acknowledged
renderer frame, its NMI reapplies the cache's existing BG register tail. Its
candidate ROM `3b7000…` starts from the same 51-column/`BG1HOFS=288` legacy-Mesen
checkpoint input and clears the strip after exactly one neutral vblank, with no
game tick, in both native configurations
(`build/validate-stage3-scroll-nmi-cache-reapply-candidate-3b7000-v2/summary.json`).
The same candidate's cold-boot one-credit legacy-Mesen HUD result is green.
The active production image remains `5c7e…`; Nexen loads that old Mesen state
as tick-zero boot rather than Stage 3, and MAME has no serialized SNES PPU
counterpart. Therefore this is a renderer/stale-state candidate result, not
fresh Stage-3, three-way gameplay, or rate acceptance.

A current-hash checkpoint probe makes the classification more precise:
`build/validation-stage3-scroll-input-current-f369-v1/summary.json` loads the supplied
`stage3.mss` in exact Mesen with the selected ROM's video mirror refreshed. Both
native-off and native-on begin at the same stale `BG1HOFS=288` frame with a
51-column solid-blue gap, then receive exactly 60 right and 60 neutral video
frames. Both clear the gap, publish a non-288 scroll (`40` native-off, `56`
native-on), retain halt zero and valid task stacks, and finish with no detected
blue-gap columns. The native-off path advances only 2 game ticks in that window
versus 32 native-on, which explains why the final hscroll values need not match
and is additional evidence that the Stage 3 rate remains open. This proves stale
PPU/renderer-state recovery on the current ROM, not fresh organic Stage 3 entry; the
initial save-state frame still needs an explicit migration or organic Stage 3 proof.

## Fresh campaign result

`build/fresh-campaign-current-4359-to10000-exact-v1/summary.json` is green on
the predecessor hash `4359…`. It starts from power-on, crosses the old 779-entry boundary,
processes 1,031 real controller transitions through MAME tick 10,000, and
records no MAME/native-on oracle divergence or SA-1 halt. It observes walking,
Button 1 punch/charge, Button 2 kick, Up flight, Down movement, crate pickup
phases, carried-crate state, crate throw, hurt/death/respawn states, and five
retained deaths. The run records no boss event or Stage 3 transition; it is a
strong bounded organic campaign, not a full playthrough. Its exact pre-death
states and controller comparisons are retained in `events.jsonl` and `states/`.

The shorter `build/fresh-campaign-current-4359-to2000-exact-v1` remains as the
earlier bounded checkpoint record; it is not the final campaign verdict.

A post-fix fresh current-hash replay is complete under
`build/fresh-campaign-current-f369-to10158-v2/summary.json`: it starts from
power-on with `TESTFLAG=0`, processes 1,068 real controller transitions through
MAME tick 10,158, records five deaths, and has zero MAME/native-on oracle
divergences and zero SA-1 halts. It reaches the repaired `$025110` boundary
without the predecessor x mismatch. It still records no boss event or Stage 3
transition, so it is bounded organic coverage, not a full playthrough; exact
boss/Stage 3 behavior is covered only by the focused fixtures above.

The current campaign's exact MAME provenance is snap revision 4339, SHA-256
`297843036f728695878300f3bd9949122907cd83bfd6d501875e9a49cd950c6f`; the
binary was recovered under `/tmp/mame-4339-recovery/root/mame` because the
historical `/snap/mame/4339/mame` mount is unavailable. The campaign retained
fresh cold-title, credited prompt, Button 1, Button 2, tick-10,000, death, and
campaign-end screens/states. It remains bounded fresh-boot evidence, not a full
playthrough.

## Fresh Stage 3 scheduler forensic result

The later authenticated fresh-lineage continuation retained a resumable
pre-failure state at
`build/forensic-fresh-stage3-rng-safe14743-v1/states/safe-checkpoint-14743.mss`.
It is a recovery checkpoint descended from a power-on campaign of this exact
`f369…` ROM; it is not the supplied `stage3.mss` and is not renderer proof.
At MAME logical tick 14,746, the arcade has saved task 15 at `$0259B0`, return
`$0242BE`, SR `$2400`, and D7 `$001B`; current SNES completes the batch to
`$0818` before delivering its virtual IRQ and still has `$02429C`/`$00044E`.
The resulting RNG/task-stack/work-RAM divergence is deterministic.

The exact three-way gate
`build/validation-stage3-irq-order-all-native-off-current-f369-v1.json` is red
from this same authenticated state. MAME, full all-escape-off SNES, and
production native-on agree on the complete task frame and game-owned regions at
ticks 14,744–14,745. At 14,746 both SNES configurations retain the wrong
`$02429C` frame while MAME has `$0259B0`; all-escape-off needs 22,461,060 SA-1
cycles/125 video frames for that interval and native-on needs 3,690,322/21.
The defined `$071A/$073A` native-off control independently reaches the same bad
frame. This classifies the fault as a hardware-boundary/virtual-IRQ timing defect,
not an interpreter or native/HLE discrepancy.

The older supplemental uninterrupted arcade trace
`build/mame-scheduler-order-f369-t14745-14747-v1/summary.json` retains 83
read-only scheduler/task/IRQ observations over ticks 14,745–14,747. It confirms
that the level-6 vector is interleaved with task 15 in this exact window, but
does not expose a usable MAME cycle counter through this Lua binding; it is
ordering evidence, not a timing-budget calibration or a fix.

The separate debugger-trace capture
`build/mame-25110-irq-phase-current-f369-v5/summary.json` does expose MAME's
exact `totalcycles` value. Its green artifact regression
`build/validation-mame-25110-irq-phase-current-f369-v5.json` records 139,302,
139,296, and 139,342 MC68000 cycles between the four level-6 services, with
interruptions at `$000818`, `$0259B0`, `$02582E`, and `$000810`. At tick 14,746
the service is at the `$02582E` collision-loop boundary. The read-only reducer
`build/analysis-mame-25110-irq-cycle-model-current-f369-v1.json` additionally
shows path-dependent costs at identical original PCs/opcodes (including the
stage-3 DBRA and branch loops). The exact-MAME static-table audit
`build/audit-m68k-cycle-model-current-f369-v6.json` covers 46,874 comparable
ROM-resident pairs: 38,888 have the development-only static-table cost and
7,986 disagree at branch/loop, MOVEM, shift/rotate, multiply/divide, or other
sites; 21 work-RAM-code pairs are explicitly excluded because the debugger
trace retains no opcode word for them. Its 46,900 pre-instruction register
rows retain a consistent two-byte debugger pipeline-PC skew. The executable
trace disproves a scalar virtual-IRQ reload or static-table-only repair: the
new timer needs path-sensitive MC68000-cycle accounting for both the
interpreter and native spans. The static-table audit itself does not attribute
every mismatch to one MAME-core mechanism. It is MAME timing evidence, not a
SNES fix, fresh Stage-3 traversal, rate result, or playthrough.

The focused register-qualified branch proof
`build/validation-mame-25110-branch-timing-current-f369-v2.json` is green.
It checks all 10,803 retained conditional-Bcc/DBcc records against the actual
pre-instruction SR/Dn state and trace successor: short Bcc 10/8, word Bcc
10/12, and DBcc branch/expired 10/14 cycles, with zero mismatches. This is a
concrete timer-regression oracle, not a complete timing model or SNES fix.

The companion variable-cost proof
`build/validation-mame-25110-variable-timing-current-f369-v2.json` is green:
all 830 retained MOVEM records match their extension-word register-list cost,
and all 452 retained data-register shifts/rotates match their immediate or
pre-instruction Dn count. The exception/arithmetic sentinel
`build/validation-mame-25110-exception-arithmetic-timing-current-f369-v1.json`
is green for 44 `TRAP #n` vector-total rows and six observed multiply/divide
operand rows. The arithmetic rows are deliberately trace-specific sentinels,
not a general timing formula, so they do not close the timer implementation or
three-way gate.

`build/validation-mame-superman-vblank-clock-current-f369-v1.json` separately
reduces the exact MAME driver declaration to `139300 + 100/5743` MC68000
cycles per vblank. The repair therefore needs a fractional phase accumulator
as well as the trace-proven completed-instruction delivery rule.

The complementary physical delivery capture
`build/capture-stage3-irq-delivery-current-f369-v3/summary.json` starts from
the same authenticated safe state, stops at the third native `$025110` entry,
then stops exactly at interpreter virtual-IRQ entry `$00:B404`. It records no
architectural writes, zero explicit `$025110` mid-call yield hits, task 15
still saved at `$02429C`/`$00044E`, and logical PC `$0818`. Its expected red
result corroborates the native-on half of the three-way failure. It is an
exact-stop checkpoint forensic, not a fresh-boot, all-native-off, rate, or
playthrough result.

A temporary literal `$2328` virtual-IRQ reload restores the first `$0259B0`
task frame, but is not a production fix: its following `$02582E` frame has the
wrong D7/A0 residue, and a slightly longer `$2354` reload already misses the
first seam. The earlier production-gated dynamic reload deadlocked at the next
coroutine boundary, while one-shot and packed-memory variants advanced to a
different MAME state. A separate `$0818` pacing-arm `$2328` probe parks task 15
at `$0818` while its tick counter advances on real video frames, so delaying the
arm is rejected as well. All experiments were removed; the current ROM remains
`f369…`. This is the root cause of the open unusable Stage 3 rate and must be
resolved with scheduler-safe IRQ delivery, then retested from a fresh boot
through this boundary and farther.

An unaccepted `VTIME=1` interpreter clock plus bounded `$025110` native ledger
is now staged separately from `f369…`. The current image
`build/interp-vtime-native-ledger-diagnostic-v2.sfc` has a green fresh 12-frame
liveness probe and a green MAME trace post-block cycle regression. The active
no-deadline exact local MAME/native-off/native-on fixture is green 2/2, and a
forced deadline prestate caught and fixed the 65816 JSR return-residue table
key. This is still neither a common native/HLE clock nor a tick-14,746 or fresh
campaign repair. An always-active-gateway draft is retained red because its
unaccepted source ROM did not reach the prompt by video frame 5,407.

The later `$02429C`-root v3 diagnostic (`3dc42f13…`) reaches 7/8 credits with
the campaign's default four-frame pre-game pulses. Per-pulse evidence isolates
the loss to pulse 2, held during frames 5,256--5,260 while game tick 82 does
not advance. Two VTIME fast-path experiments reach 71/72 rather than 69 ticks
but still finish 7/8; a one-word Select latch finishes 6/8 by delaying neutral
release publication. All three changes were reverted. The unchanged v3 ROM is
green 8/8 with eight-frame pre-game holds and gaps at
`build/probe-vtime-credit-pulses-3dc-v3-long8-v1/summary.json`. This changes
only diagnostic bootstrap duration, not the synchronized gameplay movie, and
is not a common-clock or production-input repair. Fresh disk-first Luna
controls make that limit concrete. Settle 155 reaches origin RNG 22,330, one
Lehmer step before the required 200; settle 95 reaches 28,686, 20 steps before.
Settle 158 passes origin RNG, but the first gameplay exact-entry
synchronization requests 29 `$92:DB82` occurrences and observes only 6 across
frames 5,650--8,106, with no gameplay input transitions or oracle divergence.
The compact evidence is retained in the `watcher-report.json` files under
`build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-fresh-to3000-native-on-v1/`,
`build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-wait95-fresh-to3000-native-on-v1/`,
and
`build/playback-watcher-20260808/vtime-2429c-root-3dc-long8-wait158-fresh-to3000-native-on-v1/`.
That first result was subsequently reclassified with terminal 5A22 capture.
The apparent exact-entry starvation ended in control-flow corruption rather
than an SA-1 throughput shortfall. NMI was modifying a saved status byte, and
`service_pending_dma0` left its pending publication live across `MDMAEN`; an
NMI arriving as long DMA released the CPU could recursively replay the same
descriptor until the stack returned into data. Preserving both saved status
bytes and clearing `$1F11` before DMA removed the corruption. The next bounded
run exposed a separate renderer stall: asynchronous `bg_scroll` in the NMI
keepalive clobbered renderer direct-page scratch `$D0`. Preserving `$D0`
restored continued completion.

The combined opt-in candidate is
`build/interp-vtime-2429c-root-b758-nmi-dma-d0-v1.sfc`, SHA-256
`e00fb0cbba42bb5bb92808f70f3a42f1c0080c30aa0170ab01718cadefc07051`.
Fresh native-on and matching diagnostic-tool native-off controls are bounded
partial-green through tick 250 at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-long8-wait158-to250-native-on-v1/watcher-report.json`
and
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-long8-wait158-to250-native-off-mcpdiag-v1/watcher-report.json`.
Fresh native-on then reaches tick 1,100 with exit zero, 98/98 retained
exact-entry spans, six green input transitions, 12 green player references,
valid task-stack floors, advancing render completion/generation, both CPUs
running, and no divergence at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-long8-wait158-to1100-native-on-v1/watcher-report.json`.
The retained safe checkpoint was created after tick 1,097 and authenticates
`resume_mame_tick` 1,098; the retained boundary is tick 1,099.

The first authenticated continuation uses that exact checkpoint and lineage,
with no CPU or memory transplant, and reaches tick 3,000 with exit zero at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume1098-to3000-native-on-v2/watcher-report.json`.
It adds 78 controller transitions to the six inherited from the fresh root.
The cumulative comparison is 168/168 green player references, no oracle
divergence or mismatch range, one organic death at tick 2,461, and 2/2 green
death/respawn references through the action-9 transition at tick 2,471.
Actions 0, 1, 2, 8, and 9 are now observed. At campaign end both CPUs remain
live, halt is zero, all initialized task floors are valid with minimum margin
138, and renderer state is `complete=2983`, `request=3040`, `ack=3039` with 14
queue drops. The new safe checkpoint was created after tick 2,997,
authenticates `resume_mame_tick` 2,998, and has SHA-256
`35bcb9843aee0163fdddf5c36eb874ea4b0081bec346133ec94f13ae0f059f4f`.
The next authenticated continuation starts from `resume_mame_tick` 2,998 and
reaches tick 6,000 with exit zero and no divergence or mismatch range at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume2998-to6000-native-on-v1/watcher-report.json`.
The cumulative lineage now records 567 processed input transitions,
1,134/1,134 green player references, deaths at ticks 2,461 and 4,348, and 4/4
green death/respawn references. It organically reaches the missing crate
actions: 3 at tick 3,057, 5 at tick 3,156, 4 at tick 3,208, 10 at tick 3,214,
and 7 at tick 3,216. All listed action and button gaps are therefore closed.
At tick 6,000 the CPUs are live, halt is zero, renderer state is
`complete=5981`, `request=6040`, `ack=6039` with 16 queue drops, and the
minimum task-stack margin remains 138. The newest safe checkpoint was created
after tick 5,997, authenticates `resume_mame_tick` 5,998, and has SHA-256
`1b48921fac89f4e57f6c8f6c786dcb6950af5f27289a8a1c2ad41fc98d65d73d`.
The third authenticated continuation starts from `resume_mame_tick` 5,998 and
reaches tick 10,000 with exit zero and no divergence or mismatch range at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume5998-to10000-native-on-v1/watcher-report.json`.
The cumulative lineage now records 1,031 processed input transitions,
2,062/2,062 green player references, deaths at ticks 2,461, 4,348, 7,361,
8,132, and 9,672, and 10/10 green death/respawn references. At tick 10,000 the
CPUs are live, halt is zero, renderer state is `complete=9946`,
`request=10040`, `ack=10039` with 51 queue drops, and minimum task-stack margin
is 136. The newest safe checkpoint was created after tick 9,997,
authenticates `resume_mame_tick` 9,998, and has SHA-256
`fe8e364f20b9b0e415a0c86ed7e399e8bb43bbaca8d5458496840e03df074a7c`.
This remains checkpointed sampled/transition evidence, not full per-tick
lockstep, VTIME promotion, Stage-3 rate acceptance, or a playthrough. Boss
coverage and the historical tick-14,746 ordering boundary remain open.

The first tick-14,750 continuation attempt from that state is retained
tool-red at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume9998-to14750-native-on-v1/watcher-report.json`.
It never launched a comparison because `resume_mame_tick` 9,998 coincides with
the movie's `130 -> 128` input edge. The resume harness now restores the
checkpoint's pre-edge buttons, reaches the exact tick-9,998 entry, and
compares/applies that edge exactly once. The focused regression is
`tools/test_campaign_resume_input_edge.py`. A 12-tick proof is partial-green at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume9998-to10010-input-edge-v1/watcher-report.json`:
the tick-9,998 compare and apply occur once, the tick-10,000 response is green,
and no divergence is observed. Its safe checkpoint was created after tick
10,007, authenticates `resume_mame_tick` 10,008, and has SHA-256
`f0ff546bdf69e9180612a312b0567a9978574fe48dbf0dc8d81aea4dfbe6e86d`.

The corrected Stage-3-boundary continuation starts from that exact state and
reaches tick 14,750 with exit zero and no sampled player-oracle divergence or
mismatch range at
`build/playback-watcher-20260808/vtime-2429c-root-b758-nmi-dma-d0-resume10008-to14750-native-on-v2/watcher-report.json`.
It retains exact-entry forensic states at ticks 14,743, 14,744, 14,745,
14,746, and 14,747. The tick-14,746 input compare/apply and the tick-14,747 and
14,748 response comparisons complete, after which execution remains live.
The cumulative lineage is 2,745/2,745 green player references and 12/12 green
death/respawn references. At tick 14,750 both CPUs are running, halt is zero,
minimum task-stack margin is 138, and renderer state is `complete=14668`,
`request=14790`, `ack=14789` with 79 queue drops. The post-seam safe checkpoint
created after tick 14,747 authenticates `resume_mame_tick` 14,748 and has
SHA-256
`1b1eec1f30e8ce27c71359d34b13864cff31b41db1fc006508ba601ffdfd4b61`.
It does not supersede the historical tick-14,746 ordering divergence. Exact
work-RAM attribution at
`build/playback-watcher-20260809/vtime-2429c-root-b758-nmi-dma-d0-native-on-attribution-v1/watcher-report.json`
proves task 15, RNG, and collision first split at tick 14,746 while sampled
player fields remain green; the false-hit marker splits at 14,839 and exact
player state at 14,840. The retained phase validator
`build/validate-vtime-stage3-phase-e00f-v3.json` measures a 114,978-cycle
pre-root undercharge: MAME spends 131,286 cycles before `$02429C`, VTIME
charges 16,308, and the root starts with 61,448 two-cycle units remaining even
though MAME interrupts 7,692 cycles later inside `$025110`. Route hooks record
zero native `$025110` or ESC3-ledger hits. Its pre-root inventory observes 192
known entry hits, 185 across 52 unadmitted labels. The complete
unadmitted+selected phase split is 16+0 control/scheduler, 35+2 scroll/player
prepass, 48+4 player/renderer fanout, 8+0 selector/resume tail, and 78+1
task-15 pre-root. The validator therefore records
`safe_narrow_fix_available=false`: this is broad upstream/global clock
coverage rather than a hidden child dispatch or final-root flush. The run
remains useful bounded liveness evidence, but it does not promote VTIME, make
the active ordinary `a976…` three-way gate green, establish Stage-3 rate, or
provide boss/full-playthrough coverage.

The broad phase result is now tested by an opt-in ROM-selected
interpreter-only fallback, not a debugger gate write. The image
`build/interp-vtime-interpreter-only-e00f-v1.sfc` has SHA-256
`0bfae7d05a152441f9df4d028677641420a6053ce4148711668a1c5c6b48456f`;
its manifest records one changed byte at file offset `$328000`, `$01->$03`.
The first four disk-first attempts were useful negatives: short coin pulses
under-credited, the corrected pulse width exposed the unreachable native-stop
assumption, an older diagnostic publish lacked the IRAM edge endpoint, and a
158-frame post-credit settle reached the gameplay origin exactly 69 logical
ticks early. The focused calibration at
`build/playback-watcher-20260809/vtime-interpreter-only-credit-calibration-settle1045-v1/`
then established 64-frame coin holds/gaps plus 1,045 neutral frames as the
exact credited prompt: eight pulses, credited tick 168, RNG 2716.

With that calibration and the combined diagnostic Nexen publish, the fresh v6
run at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-fresh-to250-v6/watcher-report.json`
passes the MAME tick-221/RNG-200 origin gate and remains partial-green through
tick 250 across 29/29 interpreted `$003A92` exact entries, with no first
divergence or mismatch range. The tick-250 safe rendezvous removes the IRAM
exact stop, advances the SA-1 from `$008F56` to `$008F58`, observes no second
game-update entry, and retains three byte-identical resumable non-nested saves
with SHA-256
`f49d99bf5082efb6a40cdb42f1256338c5dbf26e0c245a924a244a71142e524a`.
The preceding v5 run is retained as a harness negative: it correctly kept the
green comparison but rejected the checkpoint because virtual PC can still
read `$003A92` after the exact-stop stack is gone. The corrected contract now
requires exact-stop removal, SA-1 source-to-boundary progress, zero additional
entry hits, and repeated-save identity before treating that state as safe.
None of this promotes the fallback or proves Stage-3 rate, boss coverage, or a
full playthrough.

The subsequent tick-790 investigation initially appeared to stop after five
new interpreted `$003A92` roots. Disabling individual and combined scheduler
accelerators did not change that 5/6 observation, and splitting the exact-edge
requests across pause/resume boundaries produced the same five roots. A
non-pausing post-root trace then showed 26 `vtime_reload` executions and 26
virtual IRQ deliveries over 300 frames, ending at logical tick 819 with halt
zero. The terminal IRAM difference identified the actual classifier change:
`$071A` had become one while `$073A` remained zero. The generated bank-$F3
`$02429C` return arms all contained an unconditional gate restore after their
interpreted child returned, so the next game updates ran natively and simply
disappeared from the interpreted-edge counter. The old sentinel probe that
seemed to recover a sixth root was also reclassified: it counted the retained
initial `$003A92` state as hit one, while the exact-edge endpoint deliberately
excludes that initial match.

`tools/gen_vtime_esc5_root.py` now emits one shared mode-aware restore helper
and calls it from all eleven architectural child returns. It reads the opt-in
mode byte at `$F28000`, masks only `VTIME_FLAG_INTERPRETER_ONLY`, restores
`$071A=1` for ordinary VTIME, and leaves `$071A=0` for the interpreter-only
diagnostic. The source/generator, handoff audit, and pack regressions cover the
eleven call sites and the exact helper bytes. `tools/test_vtime_esc5_root_pack.py`
also accepts `ROM_PATH` so the preserved normal, interpreter-only, and disabled
mode images can be checked without rebuilding one mode over another.

The fixed interpreter-only artifact is
`build/interp-vtime-interpreter-only-e00f-gate-restore-v1.sfc`, SHA-256
`96d1b1935b3913400776e18c02c13591551d5e3cae98d714de80e76d118e1a99`.
The compact root-cause/fix index is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-root-cause-v1/report.json`.
The retained-state minimal run reaches 8/8 exact roots with both gates zero.
Disk-only comparison of repaired roots 6--8 against MAME ticks 796--798 finds
no scheduler, task-frame, RNG, or player-field difference; the reviewed raw
ranges are in
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-capture6-8-v1/main-review.json`.
The next run reaches roots 9--16 and is green 8/8 against MAME ticks 799--806
for the same authoritative fields at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-roots9-16-v1/watcher-report.json`.
Across those later pairs the raw work difference is 22--23 bytes: 13 are in
the SNES-only VTIME area; the remaining listed cells are boundary-local or
stable residue, and no authoritative first divergence is reached. The normal
VTIME control at
`build/playback-watcher-20260809/vtime-mode-aware-normal-gate-control-v1/watcher-report.json`
reaches the same child-return region, restores `$071A=1` with `$073A=0`, and
continues 300 frames to tick 819 with halt zero.

The decisive fresh-power-on run of the fixed hash is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-fresh-to806-v1/watcher-report.json`.
It loads no state and performs no ROM migration, CPU/memory transplant, or
debugger game-state write. It passes the tick-221/RNG-200 origin and all
585/585 interpreted entries through MAME tick 806, including the formerly
hidden post-return window. Gates remain zero, halt remains zero, render
request/ack ends 846/845, all 12 initialized task stacks remain valid with
minimum margin 138, and the three safe tick-806 saves are byte-identical at
SHA-256 `4107fc4b…`. The authenticated same-ROM continuation at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume807-to1100-v1/watcher-report.json`
adds 293/293 segment entries for 878/878 cumulative, six organic gameplay
input transitions, and 12/12 green player references. It ends at tick 1,100
with gates zero, halt zero, renderer request/ack 1140/1139, zero queue drops,
the same 138-byte minimum stack margin, and three byte-identical safe saves at
SHA-256 `adf24d89…`. The next authenticated same-ROM continuation is retained
at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume1101-to3000-v1/watcher-report.json`.
It reaches tick 3,000 with exit zero and no first divergence or mismatch range,
adding 78/78 accepted input-transition/response comparisons for 84 cumulative
transitions and 168/168 green player references. One organic death at tick
2,461 and the tick-2,471 respawn are green; actions 0/1/2/8/9 are observed.
The endpoint keeps `$071A/$073A=0/0` and halt zero; renderer state is
`request=3040`, `ack=3039`, `complete=2997`, generation 6000, and zero queue
drops. All 13 initialized task stacks are valid with minimum margin 138. The
three post-entry-safe tick-3,000 saves are byte-identical at SHA-256
`3df18b31…` and authenticate `resume_mame_tick` 3,001. Missing actions
3/4/5/7/10 and all boss events remain open. This is still a slow opt-in
correctness fallback, not a rate, boss, Stage-3 transition, ordinary-ROM, or
full-playthrough acceptance.

The first requested tick-3,001--6,000 extension is retained tool-red at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume3001-to6000-v1/watcher-report.json`.
It completed 1,964/1,964 segment exact entries through tick 4,965 before Nexen
closed MCP during a capture call (`OSError(9)`). No oracle divergence or
mismatch range preceded the transport failure. The cumulative prefix has 454
input transitions, 906/906 green player references, all action states
0/1/2/3/4/5/7/8/9/10, deaths at ticks 2,461 and 4,348, and 4/4 green
death/respawn references. It has no terminal CPU/renderer snapshot and is not
a tick-6,000 success.

The periodic tick-4,000 state in that run was an interpreted exact-entry
forensic bundle, not directly resumable. The focused recovery at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-recover4000-v3/summary.json`
loads it in a fresh Nexen process, proves the complete public machine and SA-1
IRAM byte bundle, declares the recovery load in provenance, removes the exact
stop, observes zero additional game-update entries, and saves the resulting
post-entry-safe boundary three times byte-identically at SHA-256
`786f2f72…`. It authenticates resume tick 4,001 without replaying ticks
3,001--4,000. The durable reuse policy and identity/checkpoint chain are in
`docs/current/CAMPAIGN_EVIDENCE_LEDGER.json`; the green validator is
`tools/validate_campaign_evidence_ledger.py` with focused regression
`tools/test_campaign_evidence_ledger.py`.

Five Luna-owned authenticated continuations resume that recovered checkpoint
without replaying the accepted prefix. Their compact reports are
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume{4001-to6000-v1,6001-to8000-v1,8001-to10000-v1,10001-to12000-v1,12001-to14000-v1}/watcher-report.json`.
Together they complete 9,995/9,995 segment exact entries; the lineage is green
through MAME tick 14,000 across 13,771/13,771 cumulative entries, 1,325 input
transitions, 2,650/2,650 player references, every timeline action state, six
organic deaths, and 12/12 death/respawn references, with no first divergence
or mismatch range. The tick-14,000 endpoint has `$071A/$073A=0/0`, halt zero,
renderer request/ack 14040/14039, `complete=13997`, generation 28004, zero queue
drops, and 15 valid initialized task stacks with 138-byte minimum margin. Its
three post-entry-safe states are byte-identical at SHA-256 `9a7173a1…` and
authenticate resume tick 14,001. Boss events remain 0/0. This is not a rate,
Stage-3 transition, boss, ordinary-ROM, or full-playthrough result.

The next Luna-owned continuation deliberately crosses the Stage-3 timing
window from the tick-14,000 state and stops at the first oracle discrepancy:
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-resume14001-to15000-v1/watcher-report.json`.
It completes 840/840 segment and 14,611/14,611 cumulative exact entries before
the red tick-14,841 input-response comparison. The first mismatch is the
known false respawn: MAME action 0, health 4, `(52,112)` versus SNES action 9,
health 20, `(68,96)`; the two retained controller cells still agree. Both
gameplay-native gates remain zero and halt remains zero. This reproduces under
the interpreter-only fallback the downstream signature already shared by
ordinary production-native-on and gameplay-native-off after the exact
tick-14,746 virtual-IRQ/task-frame split. It therefore reinforces the broad
common-clock root rather than identifying a native escape, collision handler,
or the repaired gate as the cause. The run retains three byte-identical safe
tick-14,743 states at SHA-256 `5ccbc509…`; the evidence ledger authenticates
resume tick 14,744 without replay. The compact artifact regression is
`tools/test_vtime_interpreter_only_stage3_divergence.py`. Continuing this
already-diverged state would prove only downstream liveness, not Stage-3
correctness, so the campaign stops at the root boundary.

The focused no-replay attribution from that tick-14,743 state is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-stage3-attribution-v1/watcher-report.json`.
The repaired fallback remains task-frame exact at ticks 14,744--14,745 and
first differs at 14,746: MAME saves `$0259B0/$0242BE`, SR `$2400`; SNES saves
`$02429C/$00044E`, SR `$2404`, with RNG/collision differences beginning in
the same tick. The retained cycle ledger measures a 114,978-cycle deficit
before `$02429C`, so the root itself is too late to be the next narrow fix.
`tools/test_vtime_interpreter_only_stage3_attribution.py` pins the compact
evidence.

The next no-replay experiment asks whether the remaining scheduler shortcuts
are a sufficient narrow cause. In explicit interpreter-only mode the source
now makes scan `$074C`, select `$075C`, switch-in `$0796`, and switch-out
`$0532` decline before architectural mutation. The corrected candidate is
`build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-fallback-v2.sfc`,
SHA-256 `60087042d9b0ecc48525258033009a634085deb661899724d917b8df78266ae9`.
An initial v1 migrated-state seam was non-testing because the old checkpoint
retained the scheduler magic gates. The per-fetch VTIME prepare path now
enforces all four interpreter-only gates for an already-valid restored clock.
The Luna-owned v2 seam at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-fallback-seam-v2/watcher-report.json`
observes `$071A/$073A/$0736/$073C=0` at every tick 14,744--14,747 boundary.
Nevertheless task 15 is exact only through 14,745 and first differs at 14,746
with the unchanged MAME `$0259B0/$0242BE`/`$2400` versus SNES
`$02429C/$00044E`/`$2404` frame; the raw mismatch counts remain
21/21/78/81. This rejects the four-shortcut fallback as sufficient and does
not justify a fresh long replay. It is ROM-migrated forensic evidence without
direct path-fire instrumentation, not Stage-3 recovery or acceptance.
`tools/test_vtime_interpreter_only_scheduler_fallback_evidence.py` guards the
validity distinction and compact negative.

The following no-replay owner reduction is
`build/playback-watcher-20260809/stage3-remaining-loop-idle-owner-scope-v1/watcher-report.json`.
It reduces 46,900 already-recorded retired MAME rows and finds `$0818` 1,993
times only in tick 14,744--14,745, then zero times in the failing
14,745--14,746 window. `$3B84/$3FEA/$ADBE` are absent there; the active
`$02429C/$025110/$0259B0` path retires 1/1/27 times. This is owner coverage,
not an oracle run. The bounded follow-up candidate
`build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-v1.sfc`
(SHA-256 `7a22b81929a491d3bf0dea96835e35d8e6fe154f13bff79cff4489559296f387`)
makes `$0818` decline before paced-helper mutation. The Luna seam at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-seam-v1/watcher-report.json`
proves the new `$99:FBB0` gateway fires 17,133 times while old `$99:FB00`
fires zero; `$071A/$073A/$0736/$073C` and halt remain zero. Yet task 15 still
first splits at tick 14,746, MAME `$0259B0` versus SNES `$02429C`, with
21/21/78/83 differing bytes. This directly rejects `$0818` pre-mutation
fallback as sufficient and does not warrant another fresh campaign replay.
`tools/test_stage3_remaining_loop_idle_owner_scope.py` and
`tools/test_vtime_interpreter_only_0818_fallback_evidence.py` pin the compact
reports. The comparison is ROM-migrated forensic evidence only. Next work
must close the active `$02429C -> $025110 -> $0259B0` child-handoff/upstream
clock ledger before proposing another timing repair.

The disk-only ledger is now
`build/playback-watcher-20260809/stage3-2429c-25110-259b0-owner-ledger-v1/watcher-report.json`.
For tick 14,745--14,746 it measures 1,554 cycles root-to-child, 1,176 to
`$02582E`, 146 to first `$0259B0`, 4,580 across 27 continuation rows, 216 to
the IRQ boundary, and a 64-cycle IRQ-entry gap. Root-to-first-continuation is
2,876 cycles, while the prior exact ledger already has 114,978 cycles missing
before root and 115,204 cycles of entry lateness. The active handoffs lack
complete common-clock ownership, but this reduction isolates no single fix.
`tools/test_stage3_2429c_25110_259b0_owner_ledger.py` guards the disk artifact.
The next seam is read-only source-authenticated observation of root, child,
resume, and IRQ transitions; it is not another long playback.

That four-tick Luna seam is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-child-hooks-v1/watcher-report.json`.
Native root/child/canonical/interpreter-branch/Stage-2/return/resume hooks are
all zero, whereas the actual IRQ entry hook fires once at each boundary and
all four fallback gates stay zero. The task-15 split remains at tick 14,746
with the same 21/21/78/83 mismatch sequence. Thus MAME's child path is not an
active accelerated SNES owner under explicit bit 1; editing those native
handlers would not address this reproduced seam. The ROM-migrated exclusion
is pinned by `tools/test_vtime_interpreter_only_root_child_hooks_evidence.py`.
The next bounded inventory targets only remaining accelerated paths that
actually fire, particularly CE4 renderer and dynamic loop families.

The Luna owner inventory is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-active-owner-inventory-v1/watcher-report.json`.
CE4 and all separately hooked unmigrated native/renderer `$AC` writers are
zero. Scheduler entries execute but their zero gates retain fallback. The
three generic-loop check labels each execute 19,262 times, an identical count
consistent with chained dispatch traversal rather than proof of an accepted
accelerated body. `$0818` gateway and IRQ controls fire as expected, and the
first split remains tick 14,746. The guard is
`tools/test_vtime_interpreter_only_active_owner_inventory.py`. Next work is a
read-only accept-versus-decline ledger inside the generic loop cluster, not a
fresh replay or blanket loop disable.

That Luna ledger is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-generic-loop-ledger-v1/watcher-report.json`.
All 19,262 matcher traversals per family decline: no memclr, verify, or memset
body is accepted, and all 1,594 word-shaped memset attempts exit without a
collapsed mutation. The first split remains tick 14,746. The bounded
no-accept result is guarded by
`tools/test_vtime_interpreter_only_generic_loop_ledger.py`. The next campaign
step is a disk-only interpreter/common-clock cycle-model comparison, not a
further fallback or long playback.

The model audit is
`build/playback-watcher-20260809/stage3-interpreter-common-clock-model-v1/watcher-report.json`.
It proves the familiar 16,308 charged versus 131,286 MAME cycles was measured
on the older preserve/native-on mixed-ledger lineage. The charge is 8,154
two-cycle units, not an instruction count and not a SHA `7a22…` bit-1 phase.
The MAME span has 11,006 instruction intervals: 9,193 static-table exact and
1,813 dynamic. Current source already performs the static-table and supported
dynamic charging per interpreted fetch, so transferring the old 114,978-cycle
gap to this candidate would be invalid. The guard is
`tools/test_stage3_interpreter_common_clock_model.py`. The filtered Luna result
is now
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-phase-v1/watcher-report.json`.
Its corrected custom-Nexen run captures 4/4 boundaries and root 1/1 after one
retained invalid zero-boundary launch against the wrong companion set. From the
tick-14,745 boundary to `$02429C`, SHA `7a22…` consumes 34,856 two-cycle units
= 69,712 MC68000 cycles without a reload or IRQ; MAME consumes 131,286. At
root, the candidate still has 69,494 virtual cycles while MAME reaches IRQ only
7,692 cycles later, a 61,802-cycle phase error. Gates and halt stay zero and
the first task-frame split stays tick 14,746. The artifact guard is
`tools/test_vtime_interpreter_only_root_phase.py`. Next is a checkpoint-bounded
interpreted-fetch count against MAME's 11,006 intervals, not a long playback.
That Luna seam is now
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-fetch-count-v1/watcher-report.json`.
It records 6,471 prepare and 6,471 consume events from boundary to root, only
58.795% of MAME's 11,006 retired intervals (deficit 4,535), with zero reloads
and IRQs. Gates and halt remain zero; ticks 14,744 and 14,745 each retain the
same 21-byte mismatch range. The guard is
`tools/test_vtime_interpreter_only_root_fetch_count.py`. This rejects a cycle-
table retune and identifies a still-skipped or collapsed path. The on-disk
logical-PC comparison is now
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-pc-sequence-v1/watcher-report.json`.
Its valid 6,471-PC reconstruction against 11,006 MAME rows has 4,551 MAME
deletions and 13 SNES insertions. The first deletion, MAME indices 223--234 at
`$0008E6…$0008D8`, follows the unconditional `$0008DE` MOVE.L run collapse at
bank-$00 `mvc_check`. It accounts for 759 deleted MOVE rows only. The largest
2,970-row deletion is dominated by `$024998` pool-scanner PCs, whose direct
native ownership is not proven with all four gates zero. The guard is
`tools/test_vtime_interpreter_only_root_pc_sequence.py`.

The VTIME boundary inventory now includes the previously omitted `mvc_check`.
A size-neutral pack patch routes VTIME images through `$F2:B4D1`; bit 1 enters
`op_move_g` before mutation and other modes retain the collapse. Candidate
`build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-v1.sfc`
is SHA `a49eedc7…`, with source/pack guard
`tools/test_vtime_interpreter_only_mvc_fallback.py`. Ordinary SHA `2dadd…` is
unchanged. The two-boundary Luna seam at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-fetch-v1/watcher-report.json`
recovers exactly 759 prepares and consumes: 6,471→7,230, exactly the deleted
MOVE-row count. Charge rises 7,590 two-cycle units to 42,446 and root remaining
falls to 27,157 units. No reload/IRQ, gate/halt, task/player, or 21-byte-range
regression is observed, but 3,776 MAME intervals remain absent. The artifact
guard is `tools/test_vtime_interpreter_only_mvc_fallback_evidence.py`. This is
a positive partial seam, not replay or acceptance. The bounded candidate PC
alignment at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-pc-v1/watcher-report.json`
shows the 759 MVC rows fully restored, with 3,792 MAME deletions and 13 SNES
insertions remaining. The first 12-row deletion does not move. The largest
2,970-row deletion is still present: MAME executes 2,096 `$0249xx` rows and
the candidate executes zero logical `$0249xx` rows. That requires a bounded
real-bank owner hook before changing the pool scanner or its caller. The guard
is `tools/test_vtime_interpreter_only_mvc_pc_sequence.py`. The owner probe at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-native-owner-v1/watcher-report.json`
then sees zero strict-window hits at `$00:D360/$D36E`, `$9D:C000`, `$9D:B000`,
or `$9D:B800`, with 7,230 prepare/consume events and no reload/IRQ. The
candidate does not enter MAME's allocator/pool path at all; native execution
does not merely conceal its logical PCs. The exclusion guard is
`tools/test_vtime_interpreter_only_root_native_owner.py`. Reduce the existing
alignment anchors and 21 differing bytes before any new emulator run.
That disk-only reduction is
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-branch-context-v1/watcher-report.json`.
The MAME-only 2,970-row path is bracketed by equal scheduler PCs `$0007E4` and
`$000766`, with no candidate logical PC between. MAME calls `$0249C2` from
`$02E8B8` and `$02498C` from `$02E8C4`. None of the 21 differing bytes is a
direct operand of the path, and 13 begin at unmapped `$F04000`; among the eight
mapped differences, the tracked game-tick low byte `$F01C57` is MAME `$97`
versus candidate `$96`. This establishes a one-count boundary offset but not
whether it causes the scheduler-path difference. Zero-advance ROM-migrated
reads of retained v6 gameplay-origin tick 221 and safe tick 250 already show
`$F01C56` one count behind MAME (`$00DA/$00DB` and `$00F7/$00F8`). The offset
therefore predates Stage 3 and cannot be a newly lost Stage-3 tick. These are
checkpoint-provenance reads, not fresh-current-candidate or acceptance
evidence. A corrected disk comparison at ticks 14,000--14,002 shows both sides
advancing `$F01C56` once per target; the separate counter that stalled was
IRAM `$0760`. The reductions prove neither an upstream deadline nor a repair.
The guards are `tools/test_vtime_interpreter_only_root_branch_context.py`,
`tools/test_vtime_interpreter_only_origin_phase_bytes.py`, and
`tools/test_vtime_interpreter_only_phase_counter_scope.py`.
The exact scheduler-selection probe next records tasks
`0,1,2,3,4,5,6,12,13,14,15`; task 13 restores `$02E864` before task 15 and
is not skipped. Its retained VTIME prepare stream nevertheless jumps directly
between exact `$0007E4/$000766` anchors, omitting all 2,970 interior MAME rows.
The disk-only IRAM-PC-write reconstruction shows that this is not a gameplay-
route omission: candidate state updates follow `$0007E8→$02E864`, twelve
ordered `$02E8B8→$0249C2→$02498C` visits, and `$000532→$000766`, matching
MAME's target counts. The defect is therefore a VTIME prepare/clock-ownership
bypass. PC writes prove ordered state values, not instruction retirement, so
the physical fetch-control owner remains the next bounded discriminator. The
guards are `tools/test_vtime_interpreter_only_root_task_selection.py`,
`tools/test_vtime_interpreter_only_root_task13_pc.py`, and
`tools/test_vtime_interpreter_only_root_task13_pcwrite.py`.
The physical control capture explains the gap: 2,971 task-13 fetches reach
`choke_tramp`, but only the first enters VTIME choke/consume/prepare. The
packed gateway's `LDA $2E` reads emulated A3.H rather than the intended
absolute `$072E` loop-arm gate. Changing only this diagnostic packing to
`LDA $072E` left the then-ordinary ROM SHA `2dadd12c…` unchanged and produced fixed
candidate `d91e28e9…`. The repeated bounded probe is 2,971/2,971 across fetch,
choke, consume, and prepare with the same task frame/gates/halt/next scan.
Boundary-to-root prepares recover from 7,230 to 11,010 versus 11,006 MAME
rows. After the known three-entry capture prefix, the former 2,970-row task-13
delete is fully aligned; only a twelve-PC delete/reinsert and terminal
candidate `$0007E8` remain. The disk-only complete-call reduction identifies
that twelve-PC order seam as equal-count palette work with different rolling
mask phase: MAME `$00030000` activates ordinals 16--17; candidate `$0000C000`
activates 14--15. Both follow task 15's
`$003B42→$003B46→$003B4C→$003B50→$0008C2` producer/caller chain. The candidate
`$F01C56/$F01C58` state is one call behind MAME, matching the offset already
present in retained zero-advance tick-221 and tick-250 states. It is therefore
checkpoint-origin phase rather than a newly lost Stage-3 execution. MAME's
intermediate mask write/read/clear is direct evidence; the candidate write is
an explicit PC-sequence/work-state inference after the bounded hook stopped
before target. This is bounded clock-coverage evidence, not a
fresh replay, rate, or acceptance claim. Guards are
`tools/test_vtime_interpreter_only_root_task13_fetch_control.py`,
`tools/test_vtime_interpreter_only_choke_gate.py`,
`tools/test_vtime_interpreter_only_choke_gate_evidence.py`,
`tools/test_vtime_interpreter_only_choke_gate_root_fetch.py`, and
`tools/test_vtime_interpreter_only_choke_gate_pc_sequence.py`,
`tools/test_vtime_interpreter_only_choke_gate_first12_context.py`,
`tools/test_vtime_interpreter_only_choke_gate_first12_mask.py`, and
`tools/test_vtime_interpreter_only_choke_gate_mask_writer.py`.

The ordinary campaign runner refuses to resume the new ROM from the old
tick-14,743 state because serialized WRAM contains the prior ROM's video
supervisor. That preserves the fresh/renderer acceptance contract. A separate
89-image forensic continuation is neither resumable nor acceptance playback;
it shows task 15 exact through tick 14,746 and different at 14,747.

The requested single-interval investigation is complete without another long
playback. On the aligned choke-gate SHA `d91e28e9…` ledger, tick 14,746
boundary-to-root charge is 61,277 two-cycle units versus MAME's 60,699:
+578 units/+1,156 cycles. Prepare and consume counts are both 10,173 and the
native-parent charges are present. The leading equal-PC discrepancies are
DBRAs, which exposed a source defect in both VTIME DBcc timing helpers: they
indexed four-byte emulated D registers with a `2*n` stride. The opt-in wrapper
fixes the lookup to `4*n` only for VTIME, producing SHA `7583d110…`; the
then-ordinary ROM remained exact SHA `2dadd12c…`.

The disk-only aligned counterfactual at
`build/playback-watcher-20260809/vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-task15-14746-boundary-root-vtwrite-v1/dbcc-stride-counterfactual.json`
replaces 493 DBcc outcomes at 22 PCs and removes 246 units/492 cycles. Its
remaining +332 units/+664 cycles decompose, after deferred native/RTS
observability cancels, into an extra candidate-only 61-row collision path
(+326), the known checkpoint-origin mask phase (+5), and +1 common-path timing
unit (`DIVU` +2, Bcc -1). This distinguishes an actual DBcc timing bug from a
work-state path difference. A single-site DIVU patch is rejected; the exact
MAME cycle core supplies no compact general operand-cycle helper.

The bounded cumulative `7583d110…` capture under
`...choke-gate-dbcc-stride-task15-14746-to14747-v1/watcher-report.json` is not
an aligned comparison: task 15 already differs at its tick-14,746 starting
boundary (`$025856` versus `$0259B0`). Its reported -19-unit endpoint therefore
does not close VTIME. A one-shot attempt to reuse the old exact tick-14,746
state under that ROM reached no requested entry in 719 frames and ended at
virtual PC `$F01B6C`, halt `$DEAD`. The state contract says
`ordinary_paused_boundary` and `resumable_checkpoint=false`; do not rerun it.

The required fresh attempt under `7583d110…` then accepted 0/8 credits. A
preserved-ROM bisect at
`build/playback-watcher-20260810/fresh-credit-bisect-v1/watcher-report-v2.json`
places the first credit failure between `60087042…` (8/8) and `7a22b819…`
(0/8), exactly at the diagnostic `$0818` pre-mutation fallback. Both CPUs are
still running in the red state, but pacing never arms and request/ack remains
64/0. The fallback skipped the paced S-CPU/NMI controller/render rendezvous;
later MVC, choke, and DBcc changes are not implicated.

The rejected pure-interpreter `$0818` path is now opt-in bit 2. Default
interpreter-only VTIME retains the paced helper and produces SHA `14e920eb…`,
while the then-ordinary SHA `2dadd12c…` remained exact. After a bounded same-ROM neutral
calibration selected a 3,224-frame credited wait, one fresh replay reached the
interpreted tick-221/RNG-200 gameplay origin and continued partial-green to
MAME tick 250 with 29 neutral gameplay ticks, zero oracle divergence, and halt
zero. Its report is
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-fresh-to250-calibrated-v1/watcher-report.json`.
The repeated safe tick-250 state is byte-identical at SHA `ba6f0490…`, its
SA-1 IRAM sidecar is `8950c547…`, and the boundary is explicitly resumable.
This establishes only a bounded fresh same-ROM lineage seed. All further
playback must resume from it in bounded checkpointed segments; the 9,432-frame
bootstrap must not be repeated. A first resume invocation used tick 250 rather
than the event's resume tick 251 and failed authentication before emulator
launch. The corrected resume reaches tick 806 with 555/555 interpreted entries
and a repeat-identical `fe4a5409…` checkpoint. Its child reaches tick 1,100
with another 293/293 entries, 12/12 green player references, six real input
transitions, zero oracle divergence, halt zero, and repeat-identical checkpoint
SHA `27207e5f…` / IRAM `5cb96e4f…`; it resumes at 1,101. This cumulative
877/877-entry result is bounded Stage-1 evidence. Stage 3, broad gameplay
inputs, rate, promotion, production acceptance, and a full playthrough remain
open.

The same exact lineage now resumes at 1,101 and reaches tick 3,000 at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume1101-to3000-v2/watcher-report.json`.
The segment is green across 1,899/1,899 interpreted entries; the authenticated
cumulative prefix is 2,776/2,776. It records 168/168 player references, 84
real input transitions, every gameplay button, actions 0/1/2/8/9, one death at
tick 2,461 with 2/2 green death references, zero oracle divergence, halt zero,
no invalid task stacks, and no render-queue drops. It has not observed actions
3/4/5/7/10 or a boss. Repeat-identical safe bundles at ticks 1,500, 2,000,
2,500, and 3,000 prevent a later run from replaying this interval. The tick-
3,000 state is SHA `47dc58a1…`, IRAM `4ee69101…`, and resumes at 3,001.

Two zero-playback negatives are retained honestly: the first 1,101 invocation
selected the wrong Nexen companion and failed identity authentication, and an
initial v2 pinned-MAME launcher preflight also failed before gameplay. The
later v2 exit-0 run uses the authenticated partial-count Nexen managed SHA
`7e15c1d8…` and supersedes both for gameplay truth. This is still bounded
Stage-1 checkpoint-continuation evidence, not Stage 3, complete controller or
action coverage, rate, promotion, production acceptance, or a playthrough.
The DBcc, fresh-bisect, paced-default, and checkpoint facts are pinned by the
focused VTIME tests in `tools/` and the current campaign evidence ledger.

The continuation requested through tick 5,000 remained oracle-green through
tick 4,559, then the Nexen MCP server closed mid-call. The compact report at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume3001-to5000-v1/watcher-report.json`
classifies this as transport-only: 1,558/1,558 segment and 4,334/4,334
cumulative entries, 763/763 player references, 382 real transitions, every
action ID, two deaths, halt zero, live rendering, and no oracle divergence.
Repeat-identical safe checkpoints exist at 3,500, 4,000, and 4,500; the last
is SHA `fb53de19…`, IRAM `be81a792…`.

The bounded recovery at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume4501-to5000-v1/watcher-report.json`
replayed only 59 already-green ticks, used `--continue-oracle-divergences`, and
completed through tick 5,000: 499/499 segment and 4,833/4,833 cumulative
entries, 921/921 player references, 85 real transitions, every action ID, two
deaths with 4/4 green death references, zero divergence, halt zero, live
rendering, and minimum task-stack margin 138. Bosses remain unobserved. The
repeat-identical tick-5,000 checkpoint is SHA `0fd2e312…`, IRAM `9e6e7605…`,
and resumes at 5,001. The transport stop invalidates no prior evidence and is
not a reason to rebuild.

The next Luna-owned same-hash report at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume5001-to6500-v1/watcher-report.json`
is partial-green through tick 6,500: 1,499/1,499 segment and 6,332/6,332
cumulative interpreted entries, 1,210/1,210 player references, 605 real input
transitions, every action ID, two deaths with 4/4 green death references, zero
divergence, halt zero, live rendering, and minimum task-stack margin 138.
Bosses remain unobserved. Repeat-identical resumable states at 5,500, 6,000,
and 6,500 cap replay cost; the last is SHA `fb9644dd…`, IRAM `26c824b3…`,
resume tick 6,501. The report consumed the existing hash and checkpoint only;
no rebuild or fresh boot occurred.

The first tick-6,501 child at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume6501-to8000-v1/`
completed no new oracle entry. Tick 6,501 is itself a resumed input edge, so
the harness had a valid zero-entry event batch and then incorrectly indexed
`spans[-1]`; its later `OSError(9)` was cleanup fallout rather than an MCP
transport loss. `tools/replay_mame_controller_campaign.py` now skips entry
execution and final-span classification for that empty batch, processes the
edge exactly once, and advances from 6,502. The focused resume-edge, lineage,
and continuation regressions are green. This invalidates only the failed child,
not the tick-6,500 parent, and requires no ROM rebuild or fresh replay.
The first corrected retry at the sibling `...resume6501-to8000-v2/` directory
was rejected in lineage preflight before emulator launch because the harness
edit changed the current runner SHA. The finite compatibility gate now admits
exactly parent runner SHA `2030c213…` for this reviewed zero-entry-only
successor; arbitrary runner drift still fails. This retained negative executed
no gameplay and invalidates nothing.

The corrected Luna-owned v3 at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume6501-to8000-v3/watcher-report.json`
is partial-green through tick 8,000: 1,499/1,499 segment and 7,831/7,831
cumulative interpreted entries, 375/375 segment and 1,585/1,585 cumulative
player references, 188 segment and 793 cumulative real input transitions,
every action ID, two deaths in this segment, 6/6 cumulative death references,
zero divergence, halt zero, live rendering, and all 15 initialized task stacks
valid with minimum margin 130. Bosses remain unobserved. Repeat-identical
resumable checkpoints exist at 7,000, 7,500, and 8,000; the last is SHA
`aea7ce50…`, IRAM `99bab411…`, resume tick 8,001. This is still same-hash
checkpoint continuation, not a rebuild or fresh boot.

The next Luna-owned same-hash report at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume8001-to9500-v1/watcher-report.json`
is partial-green through tick 9,500: 1,499/1,499 segment and 9,330/9,330
cumulative interpreted entries, 267/267 segment and 1,852/1,852 cumulative
player references, 133 segment and 926 cumulative real input transitions,
every action ID, two deaths in this segment, 8/8 cumulative death references,
zero divergence, halt zero, live rendering, and all 15 initialized task stacks
valid with minimum margin 138. Bosses remain unobserved. Repeat-identical
resumable states exist at 8,500/9,000/9,500; the last is SHA `efd193b0…`,
IRAM `fabcd919…`, resume tick 9,501. No prefix replay, rebuild, or fresh boot
occurred.

The next Luna-owned same-hash report at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume9501-to11000-v1/watcher-report.json`
is partial-green through tick 11,000: 1,499/1,499 segment and 10,829/10,829
cumulative interpreted entries, 550/550 segment and 2,402/2,402 cumulative
player references, 275 segment and 1,201 cumulative real input transitions,
every action ID, two deaths in this segment, 10/10 cumulative death references,
zero divergence, halt zero, live rendering, and all 15 initialized task stacks
valid with minimum margin 138. Bosses remain unobserved. Repeat-identical
resumable states exist at 10,000/10,500/11,000; the last is SHA `6fd49508…`,
IRAM `ef9a8033…`, resume tick 11,001. No prefix replay, rebuild, or fresh boot
occurred.

The next Luna-owned same-hash report at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume11001-to12500-v1/watcher-report.json`
is partial-green through tick 12,500: 1,499/1,499 segment and 12,328/12,328
cumulative interpreted entries, 164/164 segment and 2,566/2,566 cumulative
player references, 82 segment and 1,283 cumulative real input transitions,
every action ID, two deaths in this segment, 12/12 cumulative death references,
zero divergence, halt zero, live rendering, and all 15 initialized task stacks
valid. Minimum stack margin fell from 138 to 92 and remains a continuation
safety watch. Bosses remain unobserved. Repeat-identical resumable states exist
at 11,500/12,000/12,500; the last is SHA `0ff1242f…`, IRAM `83608462…`, resume
tick 12,501. No prefix replay, rebuild, or fresh boot occurred.

The next Luna-owned same-hash report at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume12501-to14000-v1/watcher-report.json`
is partial-green through tick 14,000: 1,499/1,499 segment and 13,827/13,827
cumulative interpreted entries, 84/84 segment and 2,650/2,650 cumulative
player references, 42 segment and 1,325 cumulative real input transitions,
every action ID, no new deaths, 12/12 cumulative death references, zero
divergence, halt zero, live rendering, and all 15 initialized task stacks
valid; minimum margin recovered to 138. Bosses remain unobserved. Repeat-
identical resumable states exist at 13,000/13,500/14,000; the last is SHA
`234ef4ad…`, IRAM `a5d1d340…`, resume tick 14,001. No prefix replay, rebuild,
or fresh boot occurred.

The Luna-owned same-hash report at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume14001-to15500-v1/watcher-report.json`
continues safely through tick 15,500 but ends the exact green prefix at 14,747.
The first divergence at tick 14,748 is player Y only: SNES 139 versus MAME 136;
action, health, X, flags, and animation match. It records 27 Y-only mismatches
at 24 sparse ticks through 14,866 and no later mismatch through 15,500. The
segment completes 1,499/1,499 entries and 15,326/15,326 cumulative entries;
halt is zero, rendering is live, and all 15 initialized stacks are valid with
minimum margin 138. End SNES game tick 15,494 versus MAME 15,500 changes the
earlier two-tick offset, so focused diagnosis from the tick-14,500 and retained
pre-failure states is testing alignment versus semantic Y drift. No Stage-
transition or boss event was emitted. Repeat-identical checkpoints exist at
14,500/15,000/15,500; the last is SHA `43f9c07c…`, IRAM `d5dff99d…`, resume
tick 15,501. The model-capacity interruption affected only the watcher turn;
the original harness continued uninterrupted. No root cause or rebuild need is
yet inferred from the sparse Y records alone.

Nearest-checkpoint focused tests initially appeared to confirm a root class
without a ROM change, but their causal conclusion is now superseded. Corrected
retirement alignment across the interpreted `$025110`
child finds 553 common rows, no PC/opcode mismatch, and no common adjusted-cost
delta; each bounded segment is exact. The prior repeated-loop `+132` claim and
the claimed `$02584A` branch mismatch used a wrong MAME interval and are
explicitly invalid. The isolated clock-accounting defect is the `$0818`
virtual-IRQ endpoint
contract: expiry leaves the staged pre-IRQ `$0818/4E75` cost live, reload does
not discard it or stage exception ownership, and `take_irq` has no VTIME cost
owner. Consequently the first ISR fetch consumes the stale cost and the final
`$000708/4EB9` cost remains staged across the first `$003A92` observation;
MAME's separate IRQ edge costs 66 cycles. The aligned first
`$003A92->$025110` span is candidate 133,046 versus MAME 133,020 cycles
(`+26`). This is a real interrupt-entry plus prepare/consume endpoint-ownership
defect, but it is not the Y-mismatch cause established by the later
counterfactuals. The compact disk result is
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume14001-to15500-v1/focused-y-write-v1/irq-cost-pipeline-v1/irq-cost-report.json`,
guarded by `tools/test_vtime_interpreter_only_irq_cost_pipeline.py`.

The superseding nearest-checkpoint diagnosis localizes the Y mismatch to input
ordering. On v4 `4a3555fd…`, a `+2` clock-seed counterfactual and a direct
one-unit countdown decrement at `$025116` both retain first divergence at
14,748. Corrected physical ordering shows the immediate `$003AD8` P1 read
36,082,626 SA-1 cycles before the next `$0818` re-arm. NMI has sampled `$0088`,
but arm=2 prevents the ordered publisher, so `$410000` stays neutral and the
candidate consumes `$FF`; MAME consumes `$EE` and moves Y 139->136. The v1
re-arm-order conclusion used a later `$003A92` occurrence and is explicitly
invalidated by `v4-input-rearm-order-v2/watcher-report.json`.

The first repair attempt, v5 `e517fb3e…`, accidentally placed its helper over
the live `$F2:B500-$B71E` dynamic cost decoder and is not gameplay evidence.
The relocated v6 `928d2e72…` runs safely but consumes the newest NMI sample
immediately, shifting the mismatch to 14,747. V7 instead patches only
`input_p1`, preserves the shared mailbox for P2/coins, uses real `$0818`
publications when `$41012B` advances, and otherwise commits the preceding
sample before staging the next. The resulting diagnostic ROM is
`build/interp-vtime-interpreter-only-paced0818-dbcc-irq-entry-vpa-input-delayed-v7.sfc`
(`45c9096d…`). Luna's ROM-only migration from the authenticated v4 tick-14,745
checkpoint is green through 14,750 with no divergence, 2,746/2,746 green player
rows, and repeat-identical tick-14,750 states. Its compact report is
`build/playback-watcher-20260811/v7-input-delayed-migrated14745-to14750-v2/watcher-report.json`.
No fresh boot or long campaign was run, so this is a focused diagnostic repair,
not a new accepted campaign lineage.

Changing this packed VTIME/IRQ contract requires a rebuilt ROM and a new hash.
No such change or rebuild has occurred, and the exact replacement
charge/handoff still needs focused proof. A new lineage would invalidate the
present hash's tick-221-through-current-boundary acceptance as evidence for the
new image, while retaining it as historical/diagnostic evidence. No fresh-boot
campaign has been started.

The next Luna-owned same-hash continuation at
`build/playback-watcher-20260810/vtime-interpreter-only-paced0818-dbcc-resume15501-to17000-v1/watcher-report.json`
reaches tick 17,000 despite the inherited red state. Halt remains zero, all 15
initialized task stacks are valid at minimum margin 138, and rendering remains
live. The segment records 38 divergences: 13 input comparisons, 14
input-response comparisons, and 11 Stage-1 boss fixtures. The compact
disk-only reduction at `focused-boss-mismatch-v1/boss-report.json` shows that
the boss rows span sparse MAME ticks 15,906--16,919 and SNES is exactly six
game ticks behind at every one. Boss initialization is expected 40 but
observed 0; the ten following observed health values are the preceding
fixture's expectation. This is moderately confident downstream timing drift,
not proof of a separate boss-health writer or collision defect. All 11 boss
fixtures are red, so this is boss-region/path coverage only. Repeat-validated
checkpoints exist at 16,000/16,500/17,000; the last is state SHA `a9826e63…`,
IRAM `cdf1a8c7…`, resume tick 17,001. No fresh boot, rebuild, or ROM edit
occurred.

The following Luna-owned continuation at
`build/playback-watcher-20260811/vtime-interpreter-only-paced0818-dbcc-resume17001-to18500-v1/watcher-report.json`
reaches tick 18,500. Three additional Stage-1 boss fixtures retain the same
one-fixture lag: expected/observed health `6/9` at tick 17,018, `2/6` at
17,560, and `$FFFF/2` at 17,654. The cumulative classes are 13 input, 14
input-response, and 14 boss divergences; all boss rows remain red and no new
causal root is isolated. Halt remains zero, every initialized stack remains
valid at minimum margin 138, and rendering remains live. Repeat-validated
checkpoints exist at 17,500/18,000/18,500; the last is state SHA `718d3dd3…`,
IRAM `a14d74b7…`, resume tick 18,501. This is same-hash forensic coverage, not
green boss or acceptance evidence.

The next Luna-owned continuation at
`build/playback-watcher-20260811/vtime-interpreter-only-paced0818-dbcc-resume18501-to20000-v1/watcher-report.json`
reaches tick 20,000 without adding an oracle-mismatch or boss-fixture row.
Cumulative counts remain 13 input, 14 input-response, and 14 boss
divergences. It processes 161 segment and 1,742 cumulative input transitions;
halt remains zero, rendering remains live, and all initialized stacks remain
valid at minimum margin 136. Repeat-validated checkpoints exist at
19,000/19,500/20,000; the last is state SHA `caf9df72…`, IRAM `f06ec2ad…`,
resume tick 20,001. No fresh boot, rebuild, or ROM edit occurred, and accepted
truth remains capped at tick 14,000.

Preserve this ROM hash after a discrepancy and continue post-divergence for
coverage when halt, task stacks, and rendering remain safe. Diagnose from the
nearest checkpoint with focused tests and batch nonblocking fixes. Luna owns
all long playback; the main thread consumes only compact watcher reports. Do
not create another ROM lineage until the confirmed root cause, rebuild need,
and invalidated fresh evidence have been reported. Do not launch a new fresh-
boot campaign without explicit user approval.

`build/playtest-investigation-20260725/campaign-stall-threeway-rom9415-v1/summary.json` is the retained-hash paired forensic run. It compares the corresponding failure against MAME and both native configurations. Native-off clears `$071A/$073A`; native-on preserves them. Both remain at the same `ispin`, registers, CCR, stack window, virtual PC/opcode, and `$DEAD` halt for 120 neutral frames. The native gates therefore do not cause or release this failure. The observed terminal is an interpreter unimplemented-opcode/invalid-PC path, with upstream PC corruption still under investigation. It is not a full playthrough or a current-hash fresh-boot result.

`tools/validate_campaign_stall.py` is an artifact-identity regression for this
failure (`build/validation-campaign-stall-current-v1.json` is green); it
deliberately does not treat the stall as acceptable behavior.

The earlier `build/supplemental-mame0289-campaign-current-v1` run reached the
same bounded coverage result with host MAME 0.289. It remains supplemental; the
current exact-0.287 run above is the authoritative fresh-campaign record.

`build/validation-13be-sentinel-route-current-v1.json` retains the pre-fix red
regression: 43 exact updates complete, all 88 observed native route hits go
through table entry `$94:AB04`, none go through direct entry `$92:A5C1`, and
every completed update loses four bytes from task 5's saved context. Entry 44
fails after the margin is exhausted. The source repair is a CE58-specific
no-push entry into the D18A body; generic D18A callers retain their normal
re-simulated return push. The rebuilt
`build/validation-13be-sentinel-route-current-v4.json` is green: 44/44 exact
entries preserve `$F00DB8`, keep the table route, avoid the direct route, and
complete without terminal failure. This is a focused boundary repair, not a
fresh-playthrough result.

## Native-stack forensic result

The exact retained boundary `states/retained-boundary-00850.mss` reproduces the
pre-fix organic native-on failure deterministically. Task 5 starts with context
`$F00DB8`, floor `$F00D0E`, and 170 bytes of margin; the old route lost four
bytes per update until entry 44. After the CE58/D18A repair, the same 44-entry
regression preserves the 170-byte margin. Native-off does not enter the native
target and retains its interpreted scheduler path.

The retained-hash entry trace is under
`build/playtest-investigation-20260725/campaign-failure-entry-trace-rom9415-v2`.
At native entry `$94:AB04` (logical 68000 PC `$13BE`), the saved stack begins
with the native sentinel `$00FD`, not a normal 68000 return PC. This classifies
the failure as a native/interpreter boundary return-frame corruption feeding
the task-stack leak. The focused valid-entry validator
`build/validation-13be-current` is green (2/2 MAME/native-off/native-on
register/CCR/work-RAM cases), so it does not cover the sentinel path. Removing
the table route changed the exact-boundary trajectory, and changing the epilogue
frame halted before the first exact update; both experiments were reverted. The
landed repair is limited to the CE58 bridge and is covered by the v3 regression.

## Newly exposed paced-collision root cause

The first post-fix replay was intentionally not allowed to resume from the old
save state. The predecessor-hash fresh run stopped at source input tick 10156
with MAME x=`184` versus native-on x=`186`; the retained pre-failure state and
SA-1 IRAM sidecar are under `build/fresh-campaign-current-4359-to10155-boundary10153-v1`.
An exact `$025110` stop at the third organic entry showed identical D/A/CCR/X,
stack, work-RAM collision records, and task order until the paced native path
omitted the outer response. The compact/fallback repair now preserves that
response and the 80-case semantic guard suite; the completed current fresh replay
is the organic confirmation for the repaired boundary.

## Stage 3 rate

The current-hash checkpointed exact-Mesen Stage 3 measurement
`build/measure-stage3-current-f369-v1.json/summary.json` reports 3.84375 video
frames/game tick and 690,322 SA-1 cycles/tick with native-on over 32 ticks;
native-off is 11,128,944.5 cycles/tick. The native speedup is real, but the
production rate still misses the 30 Hz / 358,000-cycle acceptance gate. This
remains checkpointed rate evidence, not an end-to-end FPS claim. The older
`build/measure-stage3-current-visual-v9/summary.json` is predecessor-hash evidence.

The five-tick current-hash attribution
`build/profile-stage3-tick-current-f369-v4/profile.json` reports 651,206.6
cycles/tick and 3.6 video frames/tick for that shorter checkpoint window. All
five observed `$02429C` calls took the intended empty-helper fusion path; this
rules out that fusion as the immediate cause of the rate failure. Its largest
observed cost was the `$0242BE` collision bridge (92,952.8 cycles/tick), followed
by scheduler/pacing and renderer paths. The same sample enters native `$025110`
on all five calls, then takes its Stage-4 and wide Stage-5 scans—not the repaired
Stage-2 fallback; the captured Stage-4 inner list is inactive while Stage-5 has
active wide outers. This is an attribution sample only, not a sustained
performance or fresh-entry result.

The supporting predecessor-hash (`4359…`) CE4 span profile
`build/profile-stage3-ce4-current-v3` is green for 12 ticks with 19 CE4 calls
per tick: 17 `hce4_fast_render_2x2` calls, one extended shape (`ca8e`), and one
Stage-3 panel render per tick, with no unmatched entry/exit spans. A separate
single-tick fetch attribution (`build/profile-stage3-tick-current-v1`) records
608,870 attributed cycles and identifies scheduler/idle and native-renderer
seams as the dominant spans; it is diagnostic only and does not replace the
sustained current-hash checkpoint measurement.

## Still untested or incomplete

- Current-ROM paired dynamic `$0026FA` MAME/native-off/native-on capture at the retained shake window.
- Organic boss fights, stage transitions, and a complete Stage 3/farther fresh-boot playthrough. The completed 10,158-tick route covers Down/crate/death, but no boss or Stage 3 transition.
- A current-hash fresh-lineage continuation reaches Stage 3 but has the
  deterministic tick-14,746 scheduler/IRQ ordering divergence documented above.
  There is no completed current-ROM Stage 3 traversal, boss fight, or full
  playthrough claim.
- Root repair and regression for the retained-hash `$001000B0/$F800` terminal path; the current 10,158-tick replay does not hit that halt, but it is still bounded and not a full stability proof.
- Durable payload staging for a fresh host. The default helper now accepts
  `SUPERMN_MAME_EXE` and `SUPERMN_MAME_LD_LIBRARY_PATH`, and the focused reports
  retain the extracted binary's exact hash today.
- Exact aligned Stage 3 pixels and renderer conservation through the reported vertical blue-strip state. The supplied `build/playtest/stage3.mss` has zeroed renderer-map metadata and `BG1HOFS=288`; loading it under the current ROM reproduces the blue strip but is stale-save-state evidence, not fresh-ROM proof.
- Formal current-candidate performance and real hardware.

The current bank audit is green. `build/validation-opsweep-current-v1.log`
records 782/782 `opsweep.py` cells on the current build; the attempted full `optest.py` rerun reached a harness
connection reset during the Scc group, so the accepted retained 160/160 result
remains the semantic reference rather than a new run claim.
