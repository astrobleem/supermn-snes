#!/usr/bin/env python3
"""Build an isolated R5 lab ROM for 5A22-vblank-paced $0818 waiting.

This deliberately does not edit or overwrite the canonical assembler sources,
objects, or ``build/interp.sfc``.  It creates three generated source variants:

* the $0818 clamp's 12-byte decision body becomes a size-neutral call to a
  bank-$99 lab handler, preserving every bank-$00 address and the existing
  ``INC $0760`` instruction at $00:F5A3;
* the lab handler retains the production clamp when IRAM $0734 is zero, but
  with $0734 nonzero it waits in masked ``WAI`` for a 5A22-requested SA-1 IRQ,
  then sets the virtual countdown to one;
* the WRAM-resident 5A22 supervisor requests that wake IRQ on each real vblank.

The resulting ROM is an instrumented architecture experiment, not a candidate
production build.  ``--nmi-wake`` moves the request into a 5A22 NMI handler so
rendering cannot delay it.  ``tools/profile_continuous.py --idle-vsync-lab`` is
the matching runner and records the $0734 intervention explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POPPY = Path("/home/chad/poppy/src/Poppy.CLI/bin/Release/net10.0/poppy.dll")
MARKER_OFFSET = 0x2CFF00
POLL_MARKER = b"R5VSYNC1"
NMI_MARKER = b"R5VNMI01"

INTERP_OLD = """\
    lda $AC
    cmp #$2000
    bcc lh818_pass       ; countdown already below the clamp -> let it drain
    lda #$2000
    sta $AC              ; clamp DOWN: IRQ due within ~8K instructions
"""

INTERP_LAB = """\
    jsl $99F700          ; R5 LAB: production clamp or vblank-paced WAI (gate $0734)
    bcc lh818_pass       ; handler C=0: production countdown already below clamp
    nop                  ; SIZE-NEUTRAL LAB PATCH: keep INC $0760 at exact $00:F5A3
    nop
    nop
    nop
    nop
    nop
"""

ESCBANK5_LAB = """

; =============================================================================
; R5 LAB ONLY — real-vblank-paced $0818 wait. Canonical sources do not contain
; this experiment. Called from the size-neutral bank-$00 lab patch above.
; $0734=0 preserves the shipped $2000 clamp; nonzero selects masked WAI.
; =============================================================================
.org $F700
lh_0818_vsync_lab:
    lda $0734
    bne lhvs_wait
    lda $AC
    cmp #$2000
    bcc lhvs_no
    lda #$2000
    sta $AC
    sec
    rtl
lhvs_no:
    clc
    rtl
lhvs_wait:
    php
    sei                  ; IRQ wakes WAI but cannot vector into the interpreter
    sep #$20
    lda #$80
    sta $220B            ; discard a stale request from active work
    sta $220A            ; enable S-CPU -> SA-1 IRQ as the WAI wake source
    wai
    stz $220A            ; no asynchronous SA-1 IRQs during active interpreter work
    lda #$80
    sta $220B            ; clear the request that woke us
    rep #$30
    plp
    rep #$30             ; loop_hook's documented 16-bit A/X contract
    lda #$0001
    sta $AC              ; iloop raises the virtual 68K IRQ at the next boundary
    sec                  ; common bank-$00 tail increments $0760 exactly once
    rtl
"""

VIDEO_EDGE_OLD = """\
    lda #$01
    sta $1F10            ; mark this vblank handled (edge -> one call per frame = 60Hz)
    jsl.l Tad_Process|$7F0000   ; A8/X16 already set; the $7F WRAM copy (NOT $E9 ROM - 5A22
"""

VIDEO_EDGE_LAB = """\
    lda #$01
    sta $1F10            ; mark this vblank handled (edge -> one call per frame = 60Hz)
    lda #$80             ; R5 LAB: wake a masked SA-1 WAI through the inter-CPU IRQ line
    sta $2200            ; CCNT bit7=request; reset/wait/NMI bits remain clear
    jsl.l Tad_Process|$7F0000   ; A8/X16 already set; the $7F WRAM copy (NOT $E9 ROM - 5A22
"""

NMI_TRAMPOLINE_LAB = """

; R5 NMI-WAKE LAB ONLY — bank-$00 vector trampoline in dead inline space.
; The real handler must execute from WRAM so its last Bus-A access can remain
; IRAM; returning from a ROM-hosted handler would immediately re-latch PrgRom.
.org $D1F3
nmi_vsync_lab:
    jml $7F8F00
"""

VIDEO_NMI_HANDLER_LAB = """

; R5 NMI-WAKE LAB ONLY — copied by rc_copy and executed at $7F:8F00.
; Saves full native state independent of the interrupted M/X width, requests
; the SA-1 wake, touches IRAM last to leave Nexen's hardware-shaped Bus-A latch
; off PrgRom, and returns entirely from WRAM.
.org $8F00
nmi_vsync_wram_lab:
    php
    rep #$30
    pha
    phx
    phy
    phb
    sep #$20
    lda #$00
    pha
    plb                  ; hardware registers + IRAM latch read require DBR=$00
    lda #$80
    sta $2200
    lda $3302            ; leave 5A22 Bus-A latch on IRAM, not the NMI's ROM fetch
                         ; (all following code fetches are WRAM, so it stays there)
    plb
    rep #$30
    ply
    plx
    pla
    plp
    rti
"""

WL_SETUP_OLD = """\
    rep #$30
    jml $7EF000          ; the 5A22 lives in WRAM from here on
"""

WL_SETUP_NMI = """\
    rep #$30
    sep #$20             ; R5 NMI-WAKE LAB: real vblank can preempt a long renderer
    lda #$80
    sta NMITIMEN         ; NMI on, auto-joypad remains off
    rep #$30
    jml $7EF000          ; the 5A22 lives in WRAM from here on
"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source match, found {count}")
    return text.replace(old, new, 1)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(source: Path, output: Path, symbols: Path | None = None) -> None:
    command = [
        "dotnet",
        str(POPPY),
        "-t",
        "snes",
        "-I",
        str(ROOT),
        "-o",
        str(output),
    ]
    if symbols is not None:
        command.extend(["-s", str(symbols)])
    command.append(str(source))
    subprocess.run(command, cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "build/r5-idle-vsync-lab",
    )
    parser.add_argument(
        "--nmi-wake",
        action="store_true",
        help="Request the SA-1 wake from 5A22 NMI instead of the supervisor poll loop.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not POPPY.is_file():
        raise SystemExit(f"Poppy not found: {POPPY}")

    interp_text = (ROOT / "src/interp.pasm").read_text(encoding="utf-8")
    interp_text = replace_once(
        interp_text, INTERP_OLD, INTERP_LAB, "bank-$00 size-neutral hook"
    )
    if args.nmi_wake:
        interp_text = replace_once(
            interp_text,
            ".word $0000,$0000,irq,irq,$0000,nmi,reset,irq",
            ".word $0000,$0000,irq,irq,$0000,nmi_vsync_lab,reset,irq",
            "native-mode NMI vector",
        )
        interp_text = replace_once(
            interp_text,
            ".word $0000,$0000,irq,$0000,$0000,nmi,reset,irq",
            ".word $0000,$0000,irq,$0000,$0000,nmi_vsync_lab,reset,irq",
            "emulation-mode NMI vector",
        )
        interp_text += NMI_TRAMPOLINE_LAB
    interp_text = replace_once(
        interp_text,
        '.incbin "../data/cchip_boot_response.bin"',
        f'.incbin "{ROOT / "data/cchip_boot_response.bin"}"',
        "generated-source C-Chip include path",
    )
    interp_source = output_dir / "interp_vsync_lab.pasm"
    interp_source.write_text(interp_text, encoding="utf-8")

    esc5_text = (ROOT / "src/escbank5.pasm").read_text(encoding="utf-8")
    if ".org $F700" in esc5_text:
        raise RuntimeError("canonical escbank5 now owns the lab handler address")
    esc5_source = output_dir / "escbank5_vsync_lab.pasm"
    esc5_source.write_text(esc5_text + ESCBANK5_LAB, encoding="utf-8")

    video_text = (ROOT / "src/video.pasm").read_text(encoding="utf-8")
    if args.nmi_wake:
        video_text = replace_once(
            video_text, WL_SETUP_OLD, WL_SETUP_NMI, "enable 5A22 vblank NMI"
        )
        video_text += VIDEO_NMI_HANDLER_LAB
    else:
        video_text = replace_once(
            video_text, "cpx #$0037", "cpx #$003C", "WRAM supervisor blob length"
        )
        video_text = replace_once(
            video_text, VIDEO_EDGE_OLD, VIDEO_EDGE_LAB, "vblank SA-1 wake request"
        )
    tad_parts = [
        video_text,
        (ROOT / "soundwork/tad/build/tad_blob_syms.pasm").read_text(
            encoding="utf-8"
        ),
        (ROOT / "soundwork/tad/port/tad_glue.pasm").read_text(encoding="utf-8"),
        (ROOT / "soundwork/tad/port/tad_audio.pasm").read_text(encoding="utf-8"),
    ]
    video_source = output_dir / "video_full_vsync_lab.pasm"
    video_source.write_text("".join(tad_parts), encoding="utf-8")

    env = os.environ.copy()
    env["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    env["PATH"] = "/home/chad/.dotnet10:" + env.get("PATH", "")
    os.environ.update(env)
    interp_bin = output_dir / "interp_vsync_lab.bin"
    esc5_bin = output_dir / "escbank5_vsync_lab.bin"
    video_bin = output_dir / "video_vsync_lab.bin"
    assemble(interp_source, interp_bin, output_dir / "interp_vsync_lab.sym")
    assemble(esc5_source, esc5_bin, output_dir / "escbank5_vsync_lab.sym")
    assemble(video_source, video_bin)

    interp = interp_bin.read_bytes()
    esc5 = esc5_bin.read_bytes()
    video = video_bin.read_bytes()
    if len(interp) != 0x8000:
        raise RuntimeError(f"lab interpreter is {len(interp)} bytes, expected 32768")
    if len(esc5) > 0x8000 or len(video) > 0x8000:
        raise RuntimeError("lab bank overflow")
    canonical_interp = (ROOT / "src/interp.bin").read_bytes()
    changed = [
        index for index, (before, after) in enumerate(zip(canonical_interp, interp))
        if before != after
    ]
    expected_main = set(range(0x7597, 0x75A3))
    allowed = set(expected_main)
    if args.nmi_wake:
        allowed.update(range(0x51F3, 0x5220))
        allowed.update((0x7FEA, 0x7FEB, 0x7FFA, 0x7FFB))
    if not expected_main.issubset(changed) or not set(changed).issubset(allowed):
        raise RuntimeError(
            "size-neutral bank-$00 patch changed unexpected offsets: "
            f"{[hex(index) for index in changed[:32]]}"
        )
    if interp[0x75A3:0x75A6] != bytes.fromhex("ee6007"):
        raise RuntimeError("lab moved or changed the canonical $00:F5A3 INC $0760")

    base_path = ROOT / "build/interp.sfc"
    rom = bytearray(base_path.read_bytes())
    if len(rom) != 0x400000:
        raise RuntimeError("canonical ROM is not 4 MiB")
    header_tail = bytes(rom[0xFFB0:0x10000])
    rom[0x0000:0x8000] = interp
    rom[0x8000:0x10000] = interp
    rom[0xFFB0:0x10000] = header_tail
    rom[0x7FFC:0x7FFE] = bytes.fromhex("00fc")
    if args.nmi_wake:
        rom[0xFFEA:0xFFEC] = (0xD1F3).to_bytes(2, "little")
        rom[0xFFFA:0xFFFC] = (0xD1F3).to_bytes(2, "little")
    rom[0x298000:0x2A0000] = bytes(0x8000)
    rom[0x298000:0x298000 + len(video)] = video
    rom[0x2C8000:0x2D0000] = bytes(0x8000)
    rom[0x2C8000:0x2C8000 + len(esc5)] = esc5
    marker = NMI_MARKER if args.nmi_wake else POLL_MARKER
    rom[MARKER_OFFSET:MARKER_OFFSET + len(marker)] = marker
    title = b"SUPERMAN R5 NMI LAB" if args.nmi_wake else b"SUPERMAN R5 VSYNC LAB"
    rom[0xFFC0:0xFFD5] = title[:21].ljust(21, b" ")
    if rom[0x77E0] != 0 or rom[0xF7E0] != 0:
        raise RuntimeError("lab covered production TESTFLAG")
    if rom[0x75A3:0x75A6] != bytes.fromhex("ee6007"):
        raise RuntimeError("packed lab ROM moved $00:F5A3")

    for index in range(0xFFDC, 0xFFE0):
        rom[index] = 0
    total = sum(rom) & 0xFFFF
    complement = (~total) & 0xFFFF
    rom[0xFFDC:0xFFDE] = complement.to_bytes(2, "little")
    rom[0xFFDE:0xFFE0] = total.to_bytes(2, "little")

    rom_path = output_dir / "interp_vsync_lab.sfc"
    rom_path.write_bytes(rom)
    print(f"wrote {rom_path} ({len(rom)} bytes)")
    print(f"ROM sha256 {sha256(rom_path)}")
    detail = "$7597-$75A2 + dead NMI lab space/vectors" if args.nmi_wake else "$7597-$75A2 only"
    print(f"interp lab changes {detail}; $75A3 hook preserved")
    print(f"lab marker {marker.decode()} at file ${MARKER_OFFSET:06X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
