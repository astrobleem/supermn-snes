# SPC700 software-PSG proposal evaluation

Evaluated 2026-08-12 from the local proposal
`/home/chad/supermn-snes/soundsolution.txt`, SHA-256
`512d8f70f06a044dd609c389bb35e8f569243ba05a360542089dc09957f44e31`.
The proposal is kept local by the repository's `*.txt` ignore rule; this document
retains the engineering decision without committing the source conversation.

## Verdict

The circular-BRR software PSG is a plausible SNES technique, but it is the wrong fix
for Superman's currently poor music. Do not implement it for the 21 music tracks. The
exact preserved VGM corpus contains **zero writes to YM2610 SSG registers `$00-$0D` in
all 21 tracks**, so replaying those writes into an SPC700 PSG would generate no music
and no audible improvement.

Keep the design only as a conditional sound-effect option. The music VGMs do not prove
whether arcade SFX use SSG. Before writing a driver, run a focused MAME command sweep
that retains time-stamped YM2610 port-0 writes to registers `$00-$0D` for representative
and organically observed SFX IDs. Prefer ordinary BRR samples for short, fixed effects;
a real-time PSG is justified only if the trace finds substantial sustained or dynamic
SSG behavior.

This evaluation does not soften the current audio verdict: transport and byte loading
work, but music fidelity is extremely poor and most real SFX remain unauthored.

## Decisive corpus evidence

The repository's existing ground-truth profiler was rerun over the private unpacked
pack:

```sh
python3 tools/sound/vgm_profile.py soundwork/source/vgm_unpacked/*.vgm
```

Aggregate register-write classification:

| Evidence | Result |
|---|---:|
| Tracks profiled | 21 |
| Tracks with any SSG write | **0** |
| SSG writes | **0** |
| FM channel writes, both ports | 330,956 |
| FM-global writes | 22,661 |
| ADPCM-A writes | 6,748 |
| ADPCM-B writes | 189 setup writes |

This confirms the older retained finding in
[the sound bootstrap handoff](../history/audio/SOUND_BOOTSTRAP_HANDOFF.md): the pack is
four FM channels plus ADPCM-A percussion, with no SSG music. The proposal's remaining
split—ADPCM material to BRR and FM material to samples or converted patches—is already
the broad shape of the current pipeline. It does not address the failed FM timbre and
arrangement.

The arcade 68K also sends only one-byte cue commands. Its Z80 owns the YM2610 sequencer;
the SNES does not receive a live register stream. Replaying SSG writes would therefore
also require extracting and storing a new time-stamped event stream or porting the Z80
sound program. See [SOUND_COMMAND_MAP.md](../current/SOUND_COMMAND_MAP.md).

## Feasibility if SFX evidence later justifies it

Several numerical claims in the proposal are sound:

- DSP pitch `$0400` consumes an ordinary 32 kHz BRR source at 8 kHz.
- One 16-sample BRR block lasts 2 ms at 8 kHz.
- SPC Timer 2 is clocked at 64 kHz; target `$80` gives 500 deadlines per second.
- A 32-block ring occupies `32 * 9 = 288` bytes.
- TAD's pinned driver currently does not use Timer 2, so the timer is available in
  principle.

The proposal substantially understates integration cost:

| Constraint | Consequence |
|---|---|
| TAD voice ownership | TAD models eight music channels and dynamically maps two virtual SFX channels onto DSP voices 6 and 7. Some current songs use six music channels and Game Over uses seven. Reserving a permanent PSG voice requires changes to music masks, dirty flags, key-on/off handling, SFX stealing, and affected arrangements. |
| Timer lifecycle | TAD rewrites `$F1` while loading, pausing, playing SFX while music is paused, unpausing, and starting its main loop. Every path must preserve or deliberately reset Timer 2 and drain `$FF`; merely initializing `$FC=$80` is insufficient. |
| ARAM | The 288-byte ring is only the sample payload. Code, phase/envelope/noise state, source-directory data, event queues, guard space, and alignment also consume ARAM. The retained largest-song measurement had only 1,030 bytes before the `$F000` echo buffer. `tad-compiler check` remains the hard gate. |
| Streaming safety | The S-DSP exposes no simple current-BRR-block pointer. A timed writer must establish loop/end headers and a safe lead distance, account for decoder read-ahead and driver jitter, and retain underrun telemetry. |
| Event timing | VGM writes are sample-timed. Updating virtual registers only once per 2 ms block quantizes events unless the queue retains offsets and applies changes within each generated block. |
| SSG fidelity | A faithful implementation still needs the YM2149-family clock divider, tone periods, shared noise LFSR, mixer gating, envelope shapes, logarithmic DAC curve, phase/reset behavior, and write timing. An 8 kHz square-wave generator will alias higher notes and filter-0 4-bit BRR will add quantization. |
| SPC budget | Five hundred updates per second, each synthesizing and packing 16 samples, may be viable but is unproven beside TAD. Acceptance requires a worst-case song-plus-SFX test with TAD lag telemetry and audible underrun checks. |

## Recommended audio direction

1. Capture aligned arcade/VGM and SNES output for one important cue and grade melody,
   rhythm, octave, FM timbre, envelopes, percussion, mix, pitch effects, and loop by ear.
2. Fix the actual music problem: reconstruct important FM patches with better attack and
   looped-sustain samples or deliberately author a convincing SNES arrangement. The
   five-octave-anchor experiment was packed correctly and made no noticeable audible
   improvement, so byte identity is not an acceptance criterion.
3. Trace real SFX commands in MAME, including all YM2610 register writes rather than only
   key-on fingerprints. Reuse exact ADPCM material where possible and render short FM or
   SSG effects to BRR when their behavior is fixed.
4. Reconsider the one-voice software PSG only if that SFX census proves it buys enough
   fidelity to justify a custom TAD fork, one permanently reserved voice, tight ARAM, and
   a new audio validation campaign.

No audio blob or ROM lineage was rebuilt for this evaluation.
