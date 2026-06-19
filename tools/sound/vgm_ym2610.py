#!/usr/bin/env python3
"""vgm_ym2610 — decode a Superman (YM2610/OPNB) VGM into musical events.

Produces, from the raw register/wait log:
  * per-FM-channel note events (onset/release time in 44100 Hz samples, pitch)
  * ADPCM-A percussion trigger events (time, channel, sample start/end address)

Chip facts established empirically from this pack (see vgm_profile.py):
  * Exactly 4 FM channels are used: key-on selectors {1,2,5,6}
      selector = (part<<2)|chan_in_part ; YM2610 disables chan 0 of each part.
      We index them fm 0..3 = (p0,ch1),(p0,ch2),(p1,ch1),(p1,ch2).
  * SSG is unused in this pack.
  * ADPCM-A carries percussion; ADPCM-B is unused (init writes only).

FM pitch (OPN family, verified against ymfm ymfm_opn.cpp compute_phase_step):
      fnum  = ((hi & 7)<<8) | lo          (11-bit F-number)
      block = (hi >> 3) & 7               (octave)
      f_Hz  = fnum * clock / (144 * 2**(21 - block))
  Derivation: ymfm phase_step = (fnum<<1 << block)>>2 = fnum*2**(block-1);
  FM operator rate = clock/144 (OPNA-family); one sine cycle = 2**20 phase units
  (independently confirmed by the OPM port hitting 440 Hz). Chromatic clustering
  of decoded notes confirms the fnum*2**block structure; the /144 and /2**21
  set the absolute octave.

ADPCM-A key on/off (ymfm ymfm_adpcm.cpp): write to (port1, reg 0x00); for each
set channel bit, keyonoff(!bit7) -> bit7==0 means KEY ON.
"""
from __future__ import annotations
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vgmlib

NOTE_NAMES = ["c", "c+", "d", "d+", "e", "f", "f+", "g", "g+", "a", "a+", "b"]

# FM channel index -> (port, channel-in-part). Order is the musical/voice order.
FM_CHANNELS = [(0, 1), (0, 2), (1, 1), (1, 2)]
# 0x28 key-on selector -> fm index
SELECTOR_TO_FM = {1: 0, 2: 1, 5: 2, 6: 3}


def fnum_block_to_freq(fnum: int, block: int, clock: int) -> float:
    if fnum == 0:
        return 0.0
    return fnum * clock / (144.0 * (1 << (21 - block)))


def freq_to_midi(freq: float) -> float:
    return 69.0 + 12.0 * math.log2(freq / 440.0)


def midi_to_name(midi_round: int):
    """Return (mml_note_letter, mml_octave). MML o4 c == C4 (middle C, MIDI 60)."""
    octave = midi_round // 12 - 1
    name = NOTE_NAMES[midi_round % 12]
    return name, octave


@dataclass
class NoteEvent:
    t_on: int            # onset, samples @44100
    t_off: int           # release, samples @44100 (== t_on if still held at EOF)
    fnum: int
    block: int
    freq: float
    midi: float          # fractional midi number
    held: bool = False   # True if note was still on at end of stream


@dataclass
class DrumEvent:
    t: int               # trigger time, samples @44100
    channel: int         # ADPCM-A channel 0..5
    start: int           # sample ROM start address (bytes)
    end: int             # sample ROM end address (bytes, inclusive)
    level: int           # instrument level register value


@dataclass
class Ym2610Trace:
    header: vgmlib.VgmHeader
    fm: list = field(default_factory=lambda: [[] for _ in range(4)])  # NoteEvent lists
    drums: list = field(default_factory=list)                          # DrumEvent
    drum_samples: dict = field(default_factory=dict)  # start -> dict(start,end,count,channels)
    blocks: list = field(default_factory=list)        # (block_type, size)
    loop_sample: int = 0                              # onset time of loop point, samples

    @property
    def used_fm(self):
        return [i for i in range(4) if self.fm[i]]

    @property
    def used_drum_channels(self):
        return sorted({d.channel for d in self.drums})


def decode(path) -> Ym2610Trace:
    data = vgmlib.read_vgm(path)
    h = vgmlib.parse_header(data)
    clock = h.ym2610_clock or 8000000
    tr = Ym2610Trace(header=h)

    t = [0]  # current time in samples; list for closure mutation

    # FM state ---------------------------------------------------------------
    fnum_latch = {0: 0, 1: 0}             # per-port high-byte latch (0xA4-0xA6 write)
    fm_block_freq = [(0, 0) for _ in range(4)]  # per fm index: (fnum, block)
    fm_open = [None for _ in range(4)]    # current open NoteEvent or None

    # ADPCM-A state ----------------------------------------------------------
    a_start = [0] * 6
    a_end = [0] * 6
    a_level = [0] * 6

    def reg_offset_to_fm(port, ch):
        try:
            return FM_CHANNELS.index((port, ch))
        except ValueError:
            return None

    def open_note(fmi):
        fnum, block = fm_block_freq[fmi]
        freq = fnum_block_to_freq(fnum, block, clock)
        midi = freq_to_midi(freq) if freq > 0 else 0.0
        ev = NoteEvent(t_on=t[0], t_off=t[0], fnum=fnum, block=block,
                       freq=freq, midi=midi)
        fm_open[fmi] = ev

    def close_note(fmi):
        ev = fm_open[fmi]
        if ev is not None:
            ev.t_off = t[0]
            tr.fm[fmi].append(ev)
            fm_open[fmi] = None

    def on_write(port, reg, val):
        # --- FM frequency latches (both ports share register layout) ---
        if 0xA4 <= reg <= 0xA6:
            fnum_latch[port] = val
            return
        if 0xA0 <= reg <= 0xA2:
            ch = reg - 0xA0
            fmi = reg_offset_to_fm(port, ch)
            if fmi is not None:
                hi = fnum_latch[port]
                fnum = ((hi & 0x07) << 8) | val
                block = (hi >> 3) & 0x07
                fm_block_freq[fmi] = (fnum, block)
                # If a note is currently open, update its pitch snapshot only if
                # it was opened this same instant (pre-keyon freq set). Otherwise
                # this is an in-note bend; we keep the onset pitch.
                if fm_open[fmi] is not None and fm_open[fmi].t_on == t[0]:
                    fm_open[fmi].fnum = fnum
                    fm_open[fmi].block = block
                    fm_open[fmi].freq = fnum_block_to_freq(fnum, block, clock)
                    fm_open[fmi].midi = (freq_to_midi(fm_open[fmi].freq)
                                         if fm_open[fmi].freq > 0 else 0.0)
            return
        # --- FM key on/off (port 0 reg 0x28 only) ---
        if port == 0 and reg == 0x28:
            sel = val & 0x07
            slots = (val >> 4) & 0x0F
            fmi = SELECTOR_TO_FM.get(sel)
            if fmi is None:
                return
            if slots:                      # key on (retrigger closes prior note)
                if fm_open[fmi] is not None:
                    close_note(fmi)
                open_note(fmi)
            else:                          # key off
                close_note(fmi)
            return
        # --- ADPCM-A registers (port 1) ---
        if port == 1:
            if reg == 0x00:                # key on/off control
                for ch in range(6):
                    if (val >> ch) & 1:
                        if not (val & 0x80):  # bit7==0 -> KEY ON this channel
                            st = a_start[ch] << 8
                            en = (a_end[ch] << 8) | 0xFF
                            tr.drums.append(DrumEvent(t[0], ch, st, en, a_level[ch]))
                            samp = tr.drum_samples.setdefault(
                                st, {"start": st, "end": en, "count": 0,
                                     "channels": set()})
                            samp["count"] += 1
                            samp["channels"].add(ch)
                            samp["end"] = max(samp["end"], en)
                return
            if 0x08 <= reg <= 0x0D:        # per-channel level
                a_level[reg - 0x08] = val
                return
            if 0x10 <= reg <= 0x15:        # start addr LSB
                ch = reg - 0x10
                a_start[ch] = (a_start[ch] & 0xFF00) | val
                return
            if 0x18 <= reg <= 0x1D:        # start addr MSB
                ch = reg - 0x18
                a_start[ch] = (a_start[ch] & 0x00FF) | (val << 8)
                return
            if 0x20 <= reg <= 0x25:        # end addr LSB
                ch = reg - 0x20
                a_end[ch] = (a_end[ch] & 0xFF00) | val
                return
            if 0x28 <= reg <= 0x2D:        # end addr MSB
                ch = reg - 0x28
                a_end[ch] = (a_end[ch] & 0x00FF) | (val << 8)
                return

    def on_wait(n):
        t[0] += n

    def on_block(bt, payload):
        tr.blocks.append((bt, len(payload)))

    def on_loop():
        tr.loop_sample = t[0]

    vgmlib.walk(data, h, on_write, on_wait, on_block, on_loop)

    # close any notes still held at EOF
    for fmi in range(4):
        if fm_open[fmi] is not None:
            fm_open[fmi].held = True
            close_note(fmi)

    # finalize drum sample channel sets to sorted lists for stable output
    for s in tr.drum_samples.values():
        s["channels"] = sorted(s["channels"])
    return tr


# --- self-test / validation ------------------------------------------------

def _validate(path):
    """Decode and report: note clustering (cents-off-from-chromatic), ranges."""
    tr = decode(path)
    print(f"=== {Path(path).name} ===")
    print(f"clock {tr.header.ym2610_clock}  dur {tr.header.total_seconds:.1f}s  "
          f"loop@{tr.loop_sample} samp ({tr.loop_sample/44100:.2f}s)")
    all_cents = []
    for i in tr.used_fm:
        evs = tr.fm[i]
        midis = [e.midi for e in evs if e.freq > 0]
        if not midis:
            continue
        cents = [abs((m - round(m)) * 100) for m in midis]
        all_cents += cents
        lo = midi_to_name(round(min(midis)))
        hi = midi_to_name(round(max(midis)))
        print(f"  FM{i}: {len(evs):4d} notes  range {lo[0]}{lo[1]}..{hi[0]}{hi[1]}"
              f"  median|cents-off|={sorted(cents)[len(cents)//2]:.1f}")
    if all_cents:
        med = sorted(all_cents)[len(all_cents) // 2]
        print(f"  overall median |cents off chromatic| = {med:.1f}  "
              f"({'GOOD: pitch law validated' if med < 12 else 'CHECK: not chromatic'})")
    if tr.drums:
        print(f"  ADPCM-A: {len(tr.drums)} hits, channels {tr.used_drum_channels}, "
              f"{len(tr.drum_samples)} distinct samples")
        for st, s in sorted(tr.drum_samples.items()):
            print(f"    sample @0x{st:06X}-0x{s['end']:06X} "
                  f"({s['end']-st+1}B) x{s['count']} ch{s['channels']}")
    print()


if __name__ == "__main__":
    for a in sys.argv[1:]:
        _validate(a)
