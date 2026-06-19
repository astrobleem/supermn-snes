#!/usr/bin/env python3
"""vgm2mml — convert a Superman (YM2610) VGM into a Terrific Audio Driver MML draft.

This is a *scaffold generator*, not a one-click finished song (see CONVERTSOUND.md:
"Do not expect any automatic converter to produce finished SNES-ready music"). It does
the mechanical heavy lifting accurately:

  * decodes every FM note (pitch + on/off timing) and ADPCM-A percussion trigger,
  * estimates tempo and quantizes onsets/durations to a musical grid,
  * emits an 8-voice MML draft (4 FM voices + ADPCM-A drum voices) with the loop point,
  * writes a companion notes.md documenting assumptions + instrument stubs to fill in.

The human then supplies real instruments/samples and hand-tunes against the reference WAV.

Usage:
  python3 tools/sound/vgm2mml.py "soundwork/source/vgm_unpacked/03 Main BGM 1.vgm" \
      -o soundwork/tad/mml_drafts [--bpm 125] [--zenlen 192]
"""
from __future__ import annotations
import argparse
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vgm_ym2610 as ym
from vgm_ym2610 import midi_to_name

VGM_RATE = 44100


# --- tempo estimation -----------------------------------------------------

def estimate_tempo(onsets, bpm_lo=70.0, bpm_hi=185.0, ppqn=48, step=0.25):
    """Find the BPM whose PPQN grid the onsets snap to best.

    Returns (best_bpm, mean_abs_tick_error, [top3 candidates])."""
    if len(onsets) < 4:
        return 120.0, 0.0, []
    cands = []
    bpm = bpm_lo
    while bpm <= bpm_hi:
        spt = VGM_RATE * 60.0 / bpm / ppqn       # samples per tick
        err = 0.0
        for t in onsets:
            x = t / spt
            err += abs(x - round(x))
        cands.append((err / len(onsets), bpm))
        bpm += step
    cands.sort()
    best_err, best_bpm = cands[0]
    # tie-break: among the best few, prefer the tempo closest to 130 (avoids the
    # half/double-tempo trap that scores almost identically).
    near = [c for c in cands if c[0] <= best_err * 1.05]
    near.sort(key=lambda c: abs(c[1] - 130))
    best_bpm = near[0][1]
    top3 = sorted({round(c[1]) for c in cands[:8]})
    return best_bpm, best_err, cands[:3]


# --- note-length decomposition --------------------------------------------

def _length_tokens(zenlen):
    """Tick-value -> MML length token for values that divide zenlen, plus dotted."""
    out = {}
    n = 1
    while zenlen // n >= 1 and n <= zenlen:
        if zenlen % n == 0:
            ticks = zenlen // n
            out[ticks] = str(n)
            # dotted = 1.5x ticks
            dticks = ticks * 3 // 2
            if ticks * 3 % 2 == 0 and dticks not in out:
                out[dticks] = str(n) + "."
        n += 1
    return out


def ticks_to_lengths(dur, zenlen, table):
    """Decompose a tick duration into MML length tokens joined by ties.
    Returns list of length strings, e.g. ['4.', '16']. Always terminates (1 tick
    is expressible as 'zenlen')."""
    if dur <= 0:
        return [str(zenlen)]  # minimal sounding length
    values = sorted(table.keys(), reverse=True)
    toks = []
    rem = dur
    guard = 0
    while rem > 0 and guard < 64:
        guard += 1
        for v in values:
            if v <= rem:
                toks.append(table[v])
                rem -= v
                break
        else:
            break
    return toks or [str(zenlen)]


# --- per-channel MML emission ---------------------------------------------

class ChannelEmitter:
    def __init__(self, zenlen, table, beats_per_bar_ticks):
        self.zenlen = zenlen
        self.table = table
        self.bar = beats_per_bar_ticks
        self.cur_oct = None

    def _len(self, dur):
        return "^".join(ticks_to_lengths(dur, self.zenlen, self.table))

    def emit(self, events, loop_tick, total_ticks=0, is_drum=False):
        """events: list of dicts {on, dur, note?, octave?, inst?} sorted by `on`.
        total_ticks: pad the channel with trailing rests to this length so every
        channel loops in sync and there is always content after the loop marker.
        Returns a list of (bar_comment, tokens) lines."""
        lines = []
        cur_tick = 0
        cur_inst = None
        pending = []      # tokens for the current bar line
        bar_index = 0

        def flush(comment_bar):
            nonlocal pending
            if pending:
                lines.append(("; bar %d" % comment_bar, " ".join(pending)))
                pending = []

        loop_emitted = loop_tick <= 0

        def maybe_loop(at_tick):
            nonlocal loop_emitted
            if not loop_emitted and at_tick >= loop_tick:
                pending.append("L")
                loop_emitted = True

        for ev in events:
            on = ev["on"]
            # rest to fill the gap up to this onset
            if on > cur_tick:
                gap = on - cur_tick
                # split rests at bar boundaries so the loop marker can land cleanly
                while gap > 0:
                    maybe_loop(cur_tick)
                    bar_pos = cur_tick % self.bar
                    to_bar = self.bar - bar_pos
                    chunk = min(gap, to_bar)
                    pending.append("r" + self._len(chunk))
                    cur_tick += chunk
                    gap -= chunk
                    if cur_tick % self.bar == 0:
                        flush(bar_index)
                        bar_index += 1
            maybe_loop(cur_tick)
            # instrument switch (drums) / octave (melodic)
            if is_drum:
                if ev["inst"] != cur_inst:
                    pending.append("@%d" % ev["inst"])
                    cur_inst = ev["inst"]
                head = "c"
            else:
                octv = ev["octave"]
                if octv != self.cur_oct:
                    pending.append("o%d" % octv)
                    self.cur_oct = octv
                head = ev["note"]
            dur = ev["dur"]
            # split a note across bar boundaries with ties
            while dur > 0:
                bar_pos = cur_tick % self.bar
                to_bar = self.bar - bar_pos
                chunk = min(dur, to_bar)
                seg = self._len(chunk)
                if head is not None:
                    pending.append(head + seg)
                    head = None
                else:
                    pending.append("^" + seg)
                cur_tick += chunk
                dur -= chunk
                if cur_tick % self.bar == 0:
                    flush(bar_index)
                    bar_index += 1
        # trailing rests to the full song length (keeps channels loop-synced and
        # guarantees content after the loop marker)
        while cur_tick < total_ticks:
            maybe_loop(cur_tick)
            bar_pos = cur_tick % self.bar
            chunk = min(total_ticks - cur_tick, self.bar - bar_pos)
            pending.append("r" + self._len(chunk))
            cur_tick += chunk
            if cur_tick % self.bar == 0:
                flush(bar_index)
                bar_index += 1
        flush(bar_index)
        if not loop_emitted:        # loop point at/after song end: loop whole channel
            if lines:
                lines[0] = (lines[0][0], "L " + lines[0][1])
            loop_emitted = True
        return lines


# --- main converter -------------------------------------------------------

def sanitize(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _c_of_octave(octave):
    """Frequency of C in the given MML octave (o4 c == middle C 261.626 Hz)."""
    return 261.626 * (2.0 ** (octave - 4))


def _emit_project(proj_path, stem, voices, fm_used, fm_slot, sample_ids, tr):
    """Write a compile-checkable .terrificaudio with placeholder samples.

    Per-instrument octave range = what the song actually plays, and `freq` is set
    near the TOP octave (a sample pitches down many octaves cleanly but only ~2 up),
    so the placeholder validates the song without 'octave too high' errors. The
    maintainer swaps `source`/`freq` for real samples; ranges are already minimal."""
    import json
    from make_check_project import make_placeholder_wav, ABOUT

    ph = proj_path.parent / "instruments" / "placeholder.wav"
    make_placeholder_wav(ph)
    ph_src = "instruments/placeholder.wav"

    # octave range per FM instrument name
    fm_range = {}
    for v in voices:
        if v["kind"] == "fm":
            lo, hi = fm_range.get(v["inst"], (v["octlo"], v["octhi"]))
            fm_range[v["inst"]] = (min(lo, v["octlo"]), max(hi, v["octhi"]))

    inst_list = []
    for name in fm_used:
        lo, hi = fm_range[name]
        inst_list.append({
            "name": name, "source": ph_src,
            "freq": round(_c_of_octave(hi), 3),   # native ~= top octave
            "loop": "none", "evaluator": "default",
            "ignore_gaussian_overflow": False,
            "first_octave": lo, "last_octave": hi,
            "envelope": "adsr 12 2 6 8",
            "comment": "PLACEHOLDER FM voice — replace source with a rendered "
                       "YM2610 FM patch (looped WAV) and set freq to its true pitch",
        })
    for st in sorted(sample_ids):
        idx, name = sample_ids[st]
        s = tr.drum_samples[st]
        inst_list.append({
            "name": name, "source": ph_src,
            "freq": 500.0, "loop": "none", "evaluator": "default",
            "ignore_gaussian_overflow": False,
            "first_octave": 4, "last_octave": 4,
            "envelope": "gain F127",
            "comment": f"PLACEHOLDER drum — ADPCM-A window "
                       f"0x{s['start']:06X}-0x{s['end']:06X}; extract+decode to BRR",
        })

    # TAD opens `sound_effect_file` during common-data compilation and requires at
    # least one valid SFX (an empty "" path or empty file both error). Emit one tiny
    # placeholder SFX so the project compiles; the maintainer adds real ones later.
    # Prefer a drum instrument (range 4-4, native at o4 -> always playable). TAD
    # clamps an FM instrument's playable octaves from its freq tuning, so an FM low
    # octave isn't guaranteed; fall back to an FM instrument's TOP octave (which we
    # tuned to be near-native) if there are no drums.
    if sample_ids:
        first_inst = sample_ids[sorted(sample_ids)[0]][1]
        sfx_octave = 4
    elif fm_used:
        first_inst = fm_used[0]
        sfx_octave = fm_range[first_inst][1]
    else:
        first_inst = None
        sfx_octave = 4
    sfx_fname = f"{stem}.sfx_stub.txt"          # per-track (projects share a dir)
    sfx_file = proj_path.parent / sfx_fname
    if first_inst:
        sfx_file.write_text(
            "=== sfx_stub ===\n"
            f"    set_instrument {first_inst}\n"
            f"    play_note c{sfx_octave} 8\n", encoding="utf-8")
        sfx_names = ["sfx_stub"]
    else:
        sfx_file.write_text("", encoding="utf-8")
        sfx_names = []

    song_name = ("s" + stem) if stem[:1].isdigit() else stem
    project = {
        "_about": ABOUT,
        "instruments": inst_list,
        "samples": [],
        "default_sfx_flags": {"one_channel": True, "interruptible": True},
        "high_priority_sound_effects": [],
        "sound_effects": sfx_names,
        "low_priority_sound_effects": [],
        "sound_effect_file": sfx_fname,
        "songs": [{"name": song_name, "source": f"{stem}.mml"}],
    }
    proj_path.write_text(json.dumps(project, indent=2), encoding="utf-8")


def convert(path, outdir, bpm=None, zenlen=192, ppqn=48, grid=32):
    tr = ym.decode(path)
    h = tr.header
    title = h.gd3.get("track_en") or Path(path).stem
    stem = sanitize(Path(path).stem)

    # gather onsets for tempo estimation
    onsets = []
    for i in tr.used_fm:
        onsets += [e.t_on for e in tr.fm[i]]
    onsets += [d.t for d in tr.drums]
    onsets.sort()

    if bpm is None:
        bpm, terr, top = estimate_tempo(onsets, ppqn=ppqn)
        bpm = round(bpm)
        tempo_note = f"auto-detected (mean grid error {terr:.3f} tick); candidates {[round(c[1]) for c in top]}"
    else:
        tempo_note = "user-specified (--bpm)"

    # TAD #Tempo accepts 40-157 BPM. Fold by octaves of 2 (preserves real timing
    # exactly; only relabels note values) so any detected tempo is representable.
    folded = float(bpm)
    while folded > 157:
        folded /= 2.0
    while folded < 40:
        folded *= 2.0
    if abs(folded - bpm) > 0.5:
        tempo_note += f"; folded {bpm}->{round(folded)} BPM into TAD's 40-157 range"
    bpm = round(folded)

    # Work entirely in ZenLen ticks (whole note = zenlen ticks; quarter = zenlen/4).
    # Snap onsets/durations to a musical subdivision grid so durations are clean
    # multiples (avoids tied-fragment soup from independent onset/offset rounding).
    bar_ticks = zenlen                   # one 4/4 bar = whole note = zenlen ticks
    grid_ticks = max(1, zenlen // grid)  # e.g. grid=32 -> 6 ticks (1/32 note)
    table = _length_tokens(zenlen)
    spt_zen = VGM_RATE * 240.0 / (bpm * zenlen)  # samples per ZenLen tick

    def q(samples):
        zt = samples / spt_zen
        return int(round(zt / grid_ticks)) * grid_ticks

    loop_tick = q(tr.loop_sample) if tr.loop_sample else 0
    total_ticks = q(h.total_samples)

    # --- build voice event lists ---
    voices = []   # list of dict: {letter, kind, label, events, octlo, octhi, inst_stub}
    letters = "ABCDEFGH"

    # FM voices
    for vi, fmi in enumerate(tr.used_fm):
        evs = []
        octs = []
        for e in tr.fm[fmi]:
            if e.freq <= 0:
                continue
            midi = int(round(e.midi))
            name, octave = midi_to_name(midi)
            octave = max(1, min(7, octave))
            octs.append(octave)
            evs.append({"on": q(e.t_on), "dur": max(grid_ticks, q(e.t_off) - q(e.t_on)),
                        "note": name, "octave": octave})
        if not evs:
            continue
        voices.append({"letter": letters[len(voices)], "kind": "fm",
                       "label": f"FM{fmi}", "events": evs,
                       "octlo": min(octs), "octhi": max(octs),
                       "inst": f"sm_fm{fmi}"})

    # Drum voices — one TAD voice per ADPCM-A channel actually used.
    # Map each distinct sample window to a drum instrument id.
    sample_ids = {}   # start_addr -> (inst_index, name)
    drum_inst_base = 10
    for k, st in enumerate(sorted(tr.drum_samples)):
        sample_ids[st] = (drum_inst_base + k,
                          f"sm_drum_{tr.drum_samples[st]['start']:06x}")
    for ch in tr.used_drum_channels:
        if len(voices) >= 8:
            break
        evs = []
        chan_hits = [d for d in tr.drums if d.channel == ch]
        for j, d in enumerate(chan_hits):
            on = q(d.t)
            if j + 1 < len(chan_hits):
                gap = q(chan_hits[j + 1].t) - on
            else:
                gap = zenlen // 4
            dur = min(max(grid_ticks, gap), zenlen // 4)  # one-shot gate, cap at 1/4
            inst_idx = sample_ids[d.start][0]
            evs.append({"on": on, "dur": dur, "inst": inst_idx})
        if evs:
            voices.append({"letter": letters[len(voices)], "kind": "drum",
                           "label": f"ADPCM-A ch{ch}", "events": evs,
                           "octlo": 4, "octhi": 4, "inst": None})

    # --- emit MML ---
    em = ChannelEmitter(zenlen, table, bar_ticks)
    body_lines = []
    for v in voices:
        em.cur_oct = None
        lines = em.emit(v["events"], loop_tick, total_ticks=total_ticks,
                        is_drum=(v["kind"] == "drum"))
        body_lines.append((v, lines))

    # header
    out = []
    out.append(f"#Title {title}")
    comp = h.gd3.get("author_en") or "Taito"
    out.append(f"#Composer {comp}")
    out.append("#Author vgm2mml (Superman YM2610 conversion)")
    out.append(f"#Tempo {bpm}")
    out.append(f"#ZenLen {zenlen}")
    out.append("")
    out.append("; Echo — tame defaults; tune to taste.")
    out.append("#EchoLength 32")
    out.append("#EchoFeedback 32")
    out.append("#EchoVolume 24")
    out.append("#FirFilter 64 0 0 0 0 0 0 0")
    out.append("")
    out.append("; --- instrument bindings (STUBS — replace sources in the .terrificaudio) ---")
    # FM instrument stubs (4 max)
    fm_used = sorted({v["inst"] for v in voices if v["kind"] == "fm"})
    for idx, name in enumerate(fm_used):
        out.append(f"@{idx} {name}")
    # drum instrument stubs
    for st in sorted(sample_ids):
        idx, name = sample_ids[st]
        out.append(f"@{idx} {name}")
    out.append("")

    # map FM voice inst name -> slot index
    fm_slot = {name: i for i, name in enumerate(fm_used)}

    for v, lines in body_lines:
        L = v["letter"]
        out.append(f"; ===== Voice {L}: {v['label']}  "
                   f"(octaves {v['octlo']}-{v['octhi']}) =====")
        if v["kind"] == "fm":
            slot = fm_slot[v["inst"]]
            first = lines[0] if lines else ("", "")
            out.append(f"{L} @{slot} v10")
        else:
            out.append(f"{L} v12")
        for comment, toks in lines:
            out.append(comment)
            out.append(f"{L} {toks}")
        out.append("")

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    mml_path = outdir / f"{stem}.mml"
    mml_path.write_text("\n".join(out) + "\n", encoding="utf-8")

    # --- notes.md ---
    nd = []
    nd.append(f"# {title} — vgm2mml conversion notes\n")
    nd.append(f"- Source VGM: `{Path(path).name}`")
    nd.append(f"- Chip: {'YM2610B' if h.ym2610b else 'YM2610'} @ {h.ym2610_clock} Hz")
    nd.append(f"- Duration: {h.total_seconds:.2f}s; loop start {tr.loop_sample/VGM_RATE:.2f}s "
              f"(tick {loop_tick}); loop length {h.loop_seconds:.2f}s")
    nd.append(f"- Tempo: **{bpm} BPM**, {tempo_note}")
    nd.append(f"- Grid: ZenLen {zenlen}, snapped to 1/{grid}-note grid, 4/4 assumed\n")
    nd.append("## Voices\n")
    nd.append("| MML | Source | Notes/Hits | Octaves | Instrument stub |")
    nd.append("|----|--------|-----------:|---------|-----------------|")
    for v in voices:
        cnt = len(v["events"])
        inst = v["inst"] or "(drum kit, see below)"
        nd.append(f"| {v['letter']} | {v['label']} | {cnt} | "
                  f"{v['octlo']}-{v['octhi']} | {inst} |")
    nd.append("")
    nd.append("## FM instruments to build (4 melodic voices)\n")
    nd.append("Each FM voice needs a TAD instrument. Render the YM2610 FM patch to a "
              "looped WAV, or substitute a similar SNES sample. Set `freq` to the "
              "sample's true pitch and tighten `first_octave`/`last_octave` to the range above.\n")
    nd.append("## ADPCM-A drum samples to extract\n")
    nd.append("Extract these windows from the type-0x82 sample-ROM blocks "
              "(see vgm_extract_adpcm.py), decode YM2610 ADPCM-A -> WAV, encode to BRR.\n")
    nd.append("| Instrument | ROM window | Bytes | Hits | ADPCM-A ch |")
    nd.append("|-----------|-----------|------:|-----:|-----------|")
    for st in sorted(sample_ids):
        idx, name = sample_ids[st]
        s = tr.drum_samples[st]
        nd.append(f"| @{idx} {name} | 0x{s['start']:06X}-0x{s['end']:06X} | "
                  f"{s['end']-s['start']+1} | {s['count']} | {s['channels']} |")
    nd.append("")
    nd.append("## Known limitations of the auto-conversion\n")
    nd.append("- Onset pitch is captured at key-on; FM pitch bends / LFO vibrato during a "
              "held note are not transcribed (add `MP`/portamento by ear).")
    nd.append("- Note velocity/volume is not derived from FM TL; all voices emit a flat "
              "`v` — balance against the reference WAV.")
    nd.append("- Tempo is auto-detected; if rhythm drifts, re-run with `--bpm`.")
    nd.append("- Drum durations are gate-only (until next hit); they retrigger as one-shots.")
    nd.append("- 4/4 time is assumed for bar comments only; it does not affect playback.")
    notes_path = outdir / f"{stem}.notes.md"
    notes_path.write_text("\n".join(nd) + "\n", encoding="utf-8")

    # --- project stub (.terrificaudio): compile-checkable + the skeleton to edit ---
    proj_path = outdir / f"{stem}.terrificaudio"
    _emit_project(proj_path, stem, voices, fm_used, fm_slot, sample_ids, tr)

    print(f"wrote {mml_path}")
    print(f"wrote {notes_path}")
    print(f"wrote {proj_path}")
    print(f"  tempo {bpm} BPM, {len(voices)} voices "
          f"({len([v for v in voices if v['kind']=='fm'])} FM + "
          f"{len([v for v in voices if v['kind']=='drum'])} drum), "
          f"loop tick {loop_tick}")
    return mml_path, notes_path


def main():
    ap = argparse.ArgumentParser(description="Convert a YM2610 VGM to a TAD MML draft.")
    ap.add_argument("vgm", nargs="+")
    ap.add_argument("-o", "--outdir", default="soundwork/tad/mml_drafts")
    ap.add_argument("--bpm", type=float, default=None,
                    help="override auto-detected tempo")
    ap.add_argument("--zenlen", type=int, default=192)
    ap.add_argument("--ppqn", type=int, default=48,
                    help="tempo-detection grid resolution (ticks/quarter)")
    ap.add_argument("--grid", type=int, default=32,
                    help="quantization subdivision: 32 = snap to 1/32 notes")
    args = ap.parse_args()
    for v in args.vgm:
        convert(v, args.outdir, bpm=args.bpm, zenlen=args.zenlen,
                ppqn=args.ppqn, grid=args.grid)


if __name__ == "__main__":
    main()
