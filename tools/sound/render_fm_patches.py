#!/usr/bin/env python3
"""render_fm_patches.py — turn captured YM2610 FM patches into looped TAD instrument WAVs.

Pipeline (per patch that is the DOMINANT patch of at least one (track, FM-voice)):
  1. Render a held note at the patch's modal pitch with the ymfm YM2610B core
     (tools/sound/patch_render.cpp compiled binary; real chip emulation, not an
     approximation) — 500 kHz native chip rate, mono.
  2. Resample so ONE fundamental period == exactly 64 output samples. 64 is a
     multiple of the BRR block (16), so every whole-period boundary is a legal
     BRR loop point, and the TAD instrument freq becomes exactly 32000/64 = 500 Hz.
  3. Keep a short attack (up to ATTACK_PERIODS periods), then an 8-period loop:
     amplitude-flattened across the loop window (so a decaying render still loops
     cleanly) and crossfaded end->start (kills detune/LFO beating clicks).
  4. Normalize the base patch set by one global factor (preserves the arcade FM
     mix), then apply that same factor to optional octave-anchor variants.
  5. For configured wide-range patches, render additional source octaves and
     emit note-aware mappings. This preserves pitch-dependent FM timbre and keeps
     attack time much closer to the source than shifting one sample by 2-3 octaves.

Outputs: instruments/<name>.wav + fm_instruments.json (name, freq, loop offset,
octave range, per-(track,voice) binding map for the consolidation step).
"""
from __future__ import annotations
import argparse
import array
import json
import math
import subprocess
import wave
from pathlib import Path

ATTACK_PERIODS = 16          # max attack kept before the loop (in periods)
LOOP_PERIODS = 8             # loop window length in periods
HOLD_S, TAIL_S = 1.2, 0.3    # render length (tail unused by the loop cut)

NOTE_SEMIS = {"c": 0, "c+": 1, "d": 2, "d+": 3, "e": 4, "f": 5, "f+": 6,
              "g": 7, "g+": 8, "a": 9, "a+": 10, "b": 11}


def fnum_to_freq(block, fnum, clock):
    return fnum * clock / (144.0 * (1 << (21 - block)))


def note_octave(notestr):
    # "c6" / "a+4" -> 6 / 4
    return int(notestr.lstrip("abcdefg+").lstrip("+") or 0)


def note_midi(notestr: str) -> int:
    """MML note name to MIDI integer (`c4` == 60)."""
    octave = note_octave(notestr)
    name = notestr[: -len(str(octave))]
    return NOTE_SEMIS[name] + 12 * (octave + 1)


def note_freq(name: str, octave: int) -> float:
    n = NOTE_SEMIS[name] + 12 * (octave + 1)
    return 440.0 * 2 ** ((n - 69) / 12.0)


def pick_period(last_octave: int) -> int:
    """Samples per fundamental period. The S-DSP pitch register caps at 4x, so a
    freq=32000/64=500 Hz instrument tops out at 2 kHz (~b6). Instruments that
    must reach o7 use 32 samples/period (freq 1000 -> 4 kHz ceiling)."""
    return 32 if note_freq("b", last_octave) > 2000.0 else 64


def resample_to_period(a, src_rate, f0, period):
    """Linear resample so one f0 period == period samples (dst rate = period*f0).
    Exact float ratio -> the achieved fundamental is exactly 32000/period at
    32 kHz playback (no integer-rate rounding detune)."""
    dst_rate = period * f0
    n_out = int(len(a) * dst_rate / src_rate)
    out = array.array("d", bytes(8 * n_out))
    ratio = src_rate / dst_rate
    for i in range(n_out):
        x = i * ratio
        j = int(x)
        f = x - j
        s0 = a[j]
        s1 = a[j + 1] if j + 1 < len(a) else s0
        out[i] = s0 + (s1 - s0) * f
    return out


def period_env(a, period):
    """Per-period peak envelope."""
    return [max(abs(x) for x in a[i:i + period]) or 1e-9
            for i in range(0, len(a) - period, period)]


def classify_envelope(a16, src_rate, hold_s):
    """Classify the raw ymfm render into a TAD envelope string.
    sustained -> flat gain; decaying -> ADSR approximating the FM decay."""
    win = src_rate // 100                       # 10 ms windows
    env = [max(abs(x) for x in a16[i:i + win]) or 1
           for i in range(0, int(hold_s * src_rate), win)]
    peak = max(env)
    ipk = env.index(peak)
    end = env[-1]
    if end > 0.5 * peak:
        return "gain F127", "sustained"
    # decay time: peak -> half amplitude (in seconds)
    t_half = None
    for i in range(ipk, len(env)):
        if env[i] <= peak * 0.5:
            t_half = (i - ipk) * win / src_rate
            break
    # SNES ADSR decay-rate ladder, ~time from full to sustain level (coarse)
    ladder = [(0.04, 7), (0.11, 6), (0.22, 5), (0.29, 4),
              (0.40, 3), (0.74, 2), (0.88, 1), (9.99, 0)]
    d = next(dv for t, dv in ladder if (t_half or 9.99) <= t)
    if end <= 0.1 * peak:
        return f"adsr 15 {d} 0 0", "percussive"
    sl = max(0, min(7, round(end / peak * 8) - 1))
    return f"adsr 15 {d} {sl} 10", "decaying"


def build_looped(a, period):
    """Choose attack + loop windows, flatten + crossfade the loop.
    Returns (float samples, loop_offset_samples)."""
    env = period_env(a, period)
    peak = max(env)
    xfade = period * 2
    # loop starts once the envelope settles: first period after which the
    # envelope changes < 10% per period for 4 consecutive periods, else at
    # ATTACK_PERIODS; never before period 2.
    start = ATTACK_PERIODS
    for p in range(2, min(ATTACK_PERIODS, len(env) - LOOP_PERIODS - 4)):
        window = env[p:p + 4]
        if all(abs(window[i + 1] - window[i]) < 0.10 * window[i] for i in range(3)):
            start = p
            break
    start = min(start, max(2, len(env) - LOOP_PERIODS - 2))
    ls = start * period
    ll = LOOP_PERIODS * period
    out = array.array("d", a[:ls + ll])
    # flatten: scale each loop sample so the per-period envelope stays at env[start]
    base = env[start]
    for p in range(LOOP_PERIODS):
        e = env[start + p] if start + p < len(env) else base
        g = base / e
        for i in range(period):
            out[ls + p * period + i] *= g
    # crossfade the seam: blend the loop's last xfade samples toward the signal
    # just before the loop start (which is what the loop wraps back into)
    for i in range(xfade):
        w = i / xfade
        k = ls + ll - xfade + i
        out[k] = out[k] * (1 - w) + out[ls - xfade + i] * w
    return out, ls


def patch_distance(raw_a: str, raw_b: str) -> float:
    """Timbre distance between two captured patches (raw 31-byte register dumps).
    Weighted: algorithm structure dominates, then op MUL ratios and modulator TLs,
    then envelope rates. Used to alias unrendered patches to the nearest rendered."""
    a = bytes.fromhex(raw_a)
    b = bytes.fromhex(raw_b)
    d = 0.0
    if (a[28] & 7) != (b[28] & 7):
        d += 1000.0                                   # different FM algorithm
    d += 20.0 * abs(((a[28] >> 3) & 7) - ((b[28] >> 3) & 7))   # feedback
    for s in range(4):
        d += 30.0 * abs((a[s] & 0xF) - (b[s] & 0xF))           # MUL
        d += 5.0 * abs(((a[s] >> 4) & 7) - ((b[s] >> 4) & 7))  # DT
        d += 3.0 * abs(a[4 + s] - b[4 + s])                    # TL (carriers zeroed in ident)
        for grp in range(2, 6):                                # AR/DR/SR/SL-RR
            d += 2.0 * abs(a[grp * 4 + s] - b[grp * 4 + s])
        if a[24 + s] != b[24 + s]:                             # SSG-EG
            d += 50.0
    d += 10.0 * abs(a[30] - b[30])                             # LFO
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--patches", default="soundwork/samples/fm_patches.json")
    ap.add_argument("--renderer", required=True, help="compiled patch_render binary")
    ap.add_argument("--out", default="soundwork/tad/mml_drafts/instruments")
    ap.add_argument("--tmp", default="/tmp/fm_render")
    ap.add_argument("--target-peak", type=int, default=24000)
    ap.add_argument("--extra-budget", type=int, default=2600,
                    help="BRR bytes for non-dominant patches (per-note @ switches); "
                         "the rest alias to their nearest rendered timbre")
    ap.add_argument("--octave-variants",
                    default="tools/sound/fm_octave_variants.json",
                    help="JSON octave-anchor policy for wide-range patches")
    ap.add_argument("--no-octave-variants", action="store_true",
                    help="disable the configured octave-anchor pass")
    args = ap.parse_args()

    j = json.loads(Path(args.patches).read_text())
    clock = j["ym2610_clock"]
    plist = j["patches"]

    # dominant patch per (track, voice) (kept for the legacy binding map) +
    # GLOBAL per-patch note histogram (every keyon of that patch, any voice) —
    # with per-note @ switches an instrument only has to cover its own notes.
    bindings = []
    patch_notes = {}              # pid -> {notekey: count}
    global_keyons = {}            # pid -> total keyons
    track_patch_notes = {}        # track -> pid -> {notekey: count}
    for u in j["usage"]:
        ph = {int(k): v for k, v in u["patch_hist"].items()}
        dom = max(ph, key=ph.get)
        bindings.append({"track": u["track"], "fm_voice": u["fm_voice"], "pid": dom,
                         "instrument": f"fm_p{dom:02d}"})
        for pid_s, nh in u["note_hist"].items():
            pid = int(pid_s)
            d = patch_notes.setdefault(pid, {})
            for nk, cnt in nh.items():
                d[nk] = d.get(nk, 0) + cnt
                td = track_patch_notes.setdefault(u["track"], {}).setdefault(pid, {})
                td[nk] = td.get(nk, 0) + cnt
            global_keyons[pid] = global_keyons.get(pid, 0) + sum(nh.values())

    dominants = sorted({b["pid"] for b in bindings})
    extras_ranked = sorted((p for p in patch_notes if p not in dominants),
                           key=lambda p: -global_keyons[p])
    print(f"{len(dominants)} dominant patches; {len(extras_ranked)} extra candidates "
          f"(budget {args.extra_budget}B)")

    tmp = Path(args.tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    def patch_octaves(pid):
        octs = [note_octave(nk.split("|")[0]) for nk in patch_notes[pid]]
        return min(octs), max(octs)

    def render_one(pid, period_override=None, mode_override=None, render_name=None):
        p = plist[pid]
        assert p["id"] == pid
        mode = mode_override or max(patch_notes[pid], key=patch_notes[pid].get)
        note, block, fnum = mode.split("|")
        f0 = fnum_to_freq(int(block), int(fnum), clock)
        period = period_override or pick_period(patch_octaves(pid)[1])
        label = render_name or f"p{pid}"
        wf = tmp / f"{label}.wav"
        r = subprocess.run([args.renderer, p["raw"], block, fnum,
                            str(HOLD_S), str(TAIL_S), str(wf)],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"render failed for patch {pid}: {r.stderr}")
        src_rate = int(r.stdout.split("rate=")[1].split()[0])
        w = wave.open(str(wf))
        a = array.array("h")
        a.frombytes(w.readframes(w.getnframes()))
        w.close()
        envstr, envclass = classify_envelope(a, src_rate, HOLD_S)
        rs = resample_to_period(a, src_rate, f0, period)
        looped, ls = build_looped(rs, period)
        brr = len(looped) // 16 * 9
        print(f"  {label}: modal {note} f0={f0:.1f}Hz period={period} attack={ls} "
              f"total={len(looped)} smp (~{brr}B BRR) env={envclass} [{envstr}]")
        return (looped, ls, period, note, envstr, envclass, brr)

    rendered = {}
    for pid in dominants:
        rendered[pid] = render_one(pid)
    spent = 0
    for pid in extras_ranked:
        r = render_one(pid)
        if spent + r[6] > args.extra_budget:
            print(f"  p{pid}: over extra budget ({spent}+{r[6]}B) -> alias instead")
            continue
        rendered[pid] = r
        spent += r[6]
    print(f"extras rendered: {spent}B of {args.extra_budget}B budget")

    # alias every unrendered patch to its nearest rendered timbre
    alias = {}
    for pid in patch_notes:
        if pid in rendered:
            continue
        best = min(rendered, key=lambda rp: patch_distance(
            plist[pid]["ident"], plist[rp]["ident"]))
        alias[pid] = best

    # per-INSTRUMENT octave range = union over every patch mapped to it (own + aliased)
    inst_pids = {pid: {pid} for pid in rendered}
    for pid, target in alias.items():
        inst_pids[target].add(pid)
    inst_range = {}
    for rp, pids in inst_pids.items():
        lo, hi = 9, 0
        for pid in pids:
            plo, phi = patch_octaves(pid)
            lo, hi = min(lo, plo), max(hi, phi)
        inst_range[rp] = (lo, hi)
        # the period (freq base) was chosen from the OWN patch range; widen check:
        if note_freq("b", hi) > 4000.0:
            print(f"WARNING p{rp}: merged range tops o{hi} beyond the 4x ceiling "
                  f"even at freq 1000")

    # re-render any patch whose MERGED range (own + aliased notes) needs the
    # tighter 32-sample period for the S-DSP 4x pitch ceiling
    for rp in list(rendered):
        need = 32 if note_freq("b", inst_range[rp][1]) > 2000.0 else 64
        if rendered[rp][2] != need:
            print(f"  p{rp}: merged range tops o{inst_range[rp][1]} -> re-render at period {need}")
            rendered[rp] = render_one(rp, period_override=need)

    # Render the explicitly budgeted octave anchors. The policy records the patch
    # identity as well as its numeric ID so a regenerated/reordered capture cannot
    # silently attach an anchor to the wrong timbre.
    variant_policy = None
    variant_renders = []
    if not args.no_octave_variants:
        variant_policy = json.loads(Path(args.octave_variants).read_text())
        target_track = variant_policy["target_track"]
        target_notes = track_patch_notes.get(target_track)
        if target_notes is None:
            raise SystemExit(f"octave-variant target track not found: {target_track!r}")
        variant_budget = int(variant_policy["brr_budget"])
        variant_spent = 0
        seen_variant_names = set()
        for spec in variant_policy["variants"]:
            pid = int(spec["pid"])
            if not 0 <= pid < len(plist) or plist[pid]["id"] != pid:
                raise SystemExit(f"invalid octave-variant pid {pid}")
            if plist[pid]["ident"] != spec["ident"]:
                raise SystemExit(
                    f"octave-variant p{pid:02d} identity changed; audit the policy before rendering"
                )
            octave = int(spec["octave"])
            octave_notes = {
                nk: cnt for nk, cnt in target_notes.get(pid, {}).items()
                if note_octave(nk.split("|")[0]) == octave
            }
            if not octave_notes:
                raise SystemExit(
                    f"octave-variant p{pid:02d} has no o{octave} notes in {target_track!r}"
                )
            mode = max(octave_notes, key=octave_notes.get)
            covered_pids = [pid, *(int(p) for p in spec.get("also_for", []))]
            for covered_pid in covered_pids:
                if covered_pid not in patch_notes:
                    raise SystemExit(
                        f"octave-variant p{pid:02d} covers unknown p{covered_pid:02d}"
                    )
                if covered_pid != pid:
                    base_source = alias.get(covered_pid, covered_pid)
                    old_distance = patch_distance(
                        plist[covered_pid]["ident"], plist[base_source]["ident"]
                    )
                    new_distance = patch_distance(
                        plist[covered_pid]["ident"], plist[pid]["ident"]
                    )
                    if new_distance >= old_distance:
                        raise SystemExit(
                            f"p{pid:02d} is not a closer timbre for covered p{covered_pid:02d} "
                            f"({new_distance} >= {old_distance})"
                        )
            highest_octave = max(patch_octaves(p)[1] for p in covered_pids)
            period = pick_period(highest_octave)
            name = f"fm_p{pid:02d}_o{octave}"
            if name in seen_variant_names:
                raise SystemExit(f"duplicate octave variant {name}")
            seen_variant_names.add(name)
            data = render_one(
                pid,
                period_override=period,
                mode_override=mode,
                render_name=name,
            )
            variant_spent += data[6]
            if variant_spent > variant_budget:
                raise SystemExit(
                    f"octave variants exceed BRR policy budget "
                    f"({variant_spent} > {variant_budget} bytes)"
                )
            variant_renders.append({
                "name": name,
                "source_pid": pid,
                "octave": octave,
                "covered_pids": covered_pids,
                "render": data,
            })
        print(
            f"octave variants: {variant_spent}B of {variant_budget}B policy budget "
            f"for {target_track!r}"
        )

    # The base scale intentionally excludes octave variants: rerunning this pass
    # must not change the established mix of every pre-existing FM instrument.
    scale = args.target_peak / max(max(abs(x) for x in r[0]) for r in rendered.values())

    # Build note-aware choices for every captured patch identity. Each identity
    # retains its prior base/alias sample and gains only its configured closer
    # octave anchors. MML generation selects the closest source-note anchor.
    choices_by_pid = {}
    for pid in patch_notes:
        source_pid = alias.get(pid, pid)
        base_name = f"fm_p{source_pid:02d}"
        base_note = rendered[source_pid][3]
        choices_by_pid[pid] = [{
            "name": base_name,
            "anchor_midi": note_midi(base_note),
            "source_pid": source_pid,
        }]
    for variant in variant_renders:
        anchor_note = variant["render"][3]
        choice = {
            "name": variant["name"],
            "anchor_midi": note_midi(anchor_note),
            "source_pid": variant["source_pid"],
        }
        for pid in variant["covered_pids"]:
            choices_by_pid[pid].append(choice)

    inst_octaves = {}
    inst_pids_assigned = {}
    assignment_counts = {}
    for pid, notes in patch_notes.items():
        counts = {}
        for nk, count in notes.items():
            midi = note_midi(nk.split("|")[0])
            choice = min(
                choices_by_pid[pid],
                key=lambda c: abs(midi - c["anchor_midi"]),
            )
            name = choice["name"]
            inst_octaves.setdefault(name, set()).add(note_octave(nk.split("|")[0]))
            inst_pids_assigned.setdefault(name, set()).add(pid)
            counts[name] = counts.get(name, 0) + count
        assignment_counts[str(pid)] = counts

    instruments = []
    ident_to_inst = {}
    ident_to_variants = {}
    inst_render_tl = {}
    total_brr = 0
    for pid, (samples, ls, period, note, envstr, envclass, brr) in rendered.items():
        name = f"fm_p{pid:02d}"
        out = array.array("h", (max(-32768, min(32767, int(x * scale))) for x in samples))
        wpath = outdir / f"{name}.wav"
        w = wave.open(str(wpath), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(32000)     # nominal; TAD pitch comes from freq + note
        w.writeframes(out.tobytes())
        w.close()
        assigned_octaves = inst_octaves.get(name, {note_octave(note)})
        lo, hi = min(assigned_octaves), max(assigned_octaves)
        total_brr += len(out) // 16 * 9
        instruments.append({
            "name": name, "pid": pid, "wav": f"instruments/{name}.wav",
            "freq": 32000.0 / period, "loop_offset": ls,
            "first_octave": lo, "last_octave": hi,
            "envelope": envstr, "env_class": envclass,
            "modal_note": note, "samples": len(out),
            "aliased_pids": sorted(inst_pids_assigned.get(name, set()) - {pid}),
        })
        ident_to_inst[plist[pid]["ident"]] = name
        inst_render_tl[name] = plist[pid]["min_carrier_tl"]

    for variant in variant_renders:
        name = variant["name"]
        pid = variant["source_pid"]
        samples, ls, period, note, envstr, envclass, brr = variant["render"]
        peak = max(abs(x) for x in samples) * scale
        if peak > 32767:
            print(f"WARNING {name}: scaled peak {peak:.1f} clips signed 16-bit output")
        out = array.array(
            "h", (max(-32768, min(32767, int(x * scale))) for x in samples)
        )
        wpath = outdir / f"{name}.wav"
        w = wave.open(str(wpath), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(32000)
        w.writeframes(out.tobytes())
        w.close()
        assigned_octaves = inst_octaves.get(name, {variant["octave"]})
        lo, hi = min(assigned_octaves), max(assigned_octaves)
        total_brr += len(out) // 16 * 9
        instruments.append({
            "name": name,
            "pid": pid,
            "source_pid": pid,
            "octave_variant": variant["octave"],
            "covered_pids": variant["covered_pids"],
            "wav": f"instruments/{name}.wav",
            "freq": 32000.0 / period,
            "loop_offset": ls,
            "first_octave": lo,
            "last_octave": hi,
            "envelope": envstr,
            "env_class": envclass,
            "modal_note": note,
            "samples": len(out),
            "aliased_pids": sorted(inst_pids_assigned.get(name, set()) - {pid}),
        })
        inst_render_tl[name] = plist[pid]["min_carrier_tl"]

    for pid, target in alias.items():
        ident_to_inst[plist[pid]["ident"]] = f"fm_p{target:02d}"
    for pid, choices in choices_by_pid.items():
        ident_to_variants[plist[pid]["ident"]] = [
            {"name": c["name"], "anchor_midi": c["anchor_midi"]}
            for c in choices
        ]
    Path(outdir / "fm_instruments.json").write_text(json.dumps(
        {"instruments": instruments, "bindings": bindings,
         "ym2610_clock": clock,
         "ident_to_inst": ident_to_inst,
         "ident_to_variants": ident_to_variants,
         "inst_render_tl": inst_render_tl,
         "aliases": {str(k): v for k, v in sorted(alias.items())},
         "octave_variant_policy": variant_policy,
         "octave_variant_assignments": assignment_counts,
         "total_brr_estimate": total_brr}, indent=1))
    print(f"TOTAL FM BRR ~= {total_brr} bytes across {len(instruments)} instruments "
          f"({len(alias)} patches aliased)")


if __name__ == "__main__":
    main()
