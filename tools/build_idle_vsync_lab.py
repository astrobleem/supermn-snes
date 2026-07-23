#!/usr/bin/env python3
"""Build an isolated R5 lab ROM for 5A22-vblank-paced $0818 waiting.

This deliberately does not edit or overwrite the canonical assembler sources,
objects, or ``build/interp.sfc``.  It creates three generated source variants:

* the $0818 clamp's 12-byte decision body becomes a size-neutral call to a
  bank-$99 lab handler, preserving every bank-$00 address and the existing
  ``INC $0760`` instruction at $00:F5A3;
* the lab handler retains the production clamp when IRAM $0734 is zero, but
  with $0734 nonzero it publishes quiescence and waits in masked ``WAI`` for a
  5A22-requested SA-1 IRQ, then sets the virtual countdown to one;
* 5A22 NMI advances a shared-BW-RAM vblank epoch and snapshots/wakes at the two-vblank
  deadline; the WRAM poll loop catches a deadline already missed before arming.

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
LAB_HANDLER_ADDRESS = 0xFB00
IRQ_TRAMPOLINE_ADDRESS = 0x9428
NMI_TRAMPOLINE_ADDRESS = 0x942C
POLL_MARKER = b"R5VSYNC1"
NMI_MARKER = b"R5VNMI03"

INTERP_OLD = """\
    lda $AC
    cmp #$2000
    bcc lh818_pass       ; countdown already below the clamp -> let it drain
    lda #$2000
    sta $AC              ; clamp DOWN: IRQ due within ~8K instructions
"""

INTERP_LAB = f"""\
    jsl $99{LAB_HANDLER_ADDRESS:04X}          ; R5 LAB: production clamp or vblank-paced WAI (gate $0734)
    bcc lh818_pass       ; handler C=0: production countdown already below clamp
    nop                  ; SIZE-NEUTRAL LAB PATCH: keep INC $0760 at exact $00:F5A3
    nop
    nop
    nop
    nop
    nop
"""

ESCBANK5_LAB = f"""

; =============================================================================
; R5 LAB ONLY — real-vblank-paced $0818 wait. Canonical sources do not contain
; this experiment. Called from the size-neutral bank-$00 lab patch above.
; $0734=0 preserves the shipped $2000 clamp; nonzero selects masked WAI.
; =============================================================================
.org ${LAB_HANDLER_ADDRESS:04X}
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
    lda $41012C          ; shared-window cadence marker (IRAM cross-CPU reads are unreliable)
    cmp #$A5
    beq lhvs_epoch_ready
    lda $41012A          ; initialize last release to the current 5A22 vblank epoch
    sta $41012B
    lda #$A5
    sta $41012C
lhvs_epoch_ready:
    lda #$80
    sta $220B            ; discard a stale inter-CPU request before publishing quiescence
    sta $220A            ; enable S-CPU -> SA-1 IRQ as the masked-WAI wake source
    rep #$20
    lda #$0001
    sta $410122          ; publish LAST: stable shadow is armed/quiescent
    sep #$20
lhvs_request:
    lda #$80
    sta $2209            ; event-driven SA-1 -> S-CPU IRQ: check the deadline once, no busy poll
lhvs_wai:
    wai
lhvs_woke:
    stz $2209            ; retire any request left pending because NMI won the wake race
    stz $220A            ; no asynchronous SA-1 IRQs during active interpreter work
    lda #$80
    sta $220B            ; clear the request that woke us
    lda $41012A
    sta $41012B          ; next deadline is two vblanks after this release
    rep #$20
    lda #$0002
    sta $410122          ; released; NMI/poll must not touch the live video shadow
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

NMI_TRAMPOLINE_LAB = f"""

; R5 IRQ/NMI-WAKE LAB ONLY — bank-$00 vector trampolines in the asserted-zero
; $93EE-$942F seam after the long LEA-PC bridge.  The real handlers execute
; from WRAM so their last Bus-A access can remain IRAM.
.org ${IRQ_TRAMPOLINE_ADDRESS:04X}
irq_vsync_lab:
    jml $7F8F40
.org ${NMI_TRAMPOLINE_ADDRESS:04X}
nmi_vsync_lab:
    jml $7F8F00
"""

VIDEO_NMI_HANDLER_LAB = """

; R5 NMI-WAKE LAB ONLY — copied by rc_copy and executed from WRAM.
;
; $41:012A = monotonically wrapping 5A22 vblank epoch
; $41:012B = epoch of the last SA-1 release
; $41:012C = cadence initialization marker ($A5)
; $41:0122 = arm state: 1 quiescent, 2 released, 3 snapshotting
;
; NMI advances the epoch and tries the two-vblank wake.  Publishing arm=1 raises
; an SA-1 -> S-CPU IRQ, whose WRAM handler tries the same helper exactly once. This
; catches an already-due deadline without continuously polling BW-RAM and taxing
; active SA-1 work. Both paths first claim arm=3, publish the controller sample
; captured after the previous wake decision, snapshot the seven renderer-input KiB
; from stable BW-RAM into WRAM, publish arm=2, and only then request the masked SA-1
; IRQ. No path resumes the SA-1 during acquisition. Sampling $4016 for the next tick
; happens after the wake decision, outside the SA-1's critical tick span.
; $7E:899A remains the even/odd raw-snapshot seqlock.
; $7E:1F12 is a 5A22-private real-controller cache (TAD BSS ends at $1F0F;
; $1F10 and $1F14+ are already assigned, leaving this word free).
.org $8E00
.a8
.i16
nvl_try_wake:
    lda $410122          ; proven shared BW-RAM window; low byte is the arm state
    cmp #$01
    beq nvl_arm_seen
    rts                   ; SA-1 active, already released, or another path claimed it
nvl_arm_seen:
    lda $41012A
    sec
    sbc $41012B
    cmp #$02
    bcs nvl_deadline_due
    rts                   ; preserve the 30 Hz cadence: two real vblanks per game tick
nvl_deadline_due:
    rep #$20
    lda #$0003
    sta $410122          ; claim before touching the stable live shadow
    lda $7E1F12          ; real pad sampled after the previous NMI/IRQ wake decision
    ora $410002          ; combine the current headless/harness injection word
    sta $410000          ; sole ordered mailbox publish while the SA-1 is quiescent
    lda $7E899A
    and #$FFFE
    inc a
    sta $7E899A          ; odd while channel-7 DMA replaces the raw WRAM snapshot

    sep #$20
    stz $4370            ; channel 7: mode 0, increment A-bus source
    lda #$80
    sta $4371            ; B-bus destination $2180 (WRAM data port)
    lda #$41
    sta $4374            ; source bank = stable SA-1 BW-RAM shadow
    stz $2183            ; WRAM destination bank $7E

    rep #$30
    ldx #$2000
    stx $4372
    ldy #$4800
    sty $2181
    lda #$0400
    sta $4375
    sep #$20
    lda #$80
    sta $420B            ; palette: 1 KiB

    rep #$30
    ldx #$3000
    stx $4372
    ldy #$4C00
    sty $2181
    lda #$0800
    sta $4375
    sep #$20
    lda #$80
    sta $420B            ; D0/Y + control: 2 KiB

    rep #$30
    ldx #$4000
    stx $4372
    ldy #$5400
    sty $2181
    lda #$1000
    sta $4375
    sep #$20
    lda #$80
    sta $420B            ; E0 OBJ/BG: 4 KiB

    rep #$20
    lda $7E899A
    inc a
    bne nvl_generation_done
    lda #$0002
nvl_generation_done:
    sta $7E899A          ; even: raw WRAM snapshot complete
    lda #$0002
    sta $410122          ; release ownership before raising the wake request
    sep #$20
    lda #$80
    sta $2200            ; wake only after all three DMA operations complete
    rts

; Capture the real controller for the *next* release. This routine deliberately
; touches only CPU I/O and 5A22-private WRAM, so it is safe to run after nvl_try_wake
; has resumed the SA-1 and cannot add to the measured SA-1 tick interval. DBR is zero
; in both callers. Two byte rotates are exactly the old 16-bit ROL ordering: the first
; serial bit reaches bit 15, active high.
.a8
.i16
nvl_sample_joy:
    stz $1F12
    stz $1F13
    lda #$01
    sta $4016            ; latch controllers
    stz $4016            ; begin serial shift
    ldx #$0010
nvl_sample_loop:
    lda $4016
    lsr a
    rol $1F12
    rol $1F13
    dex
    bne nvl_sample_loop
    rts

; Full-state NMI entry.  Epoch advancement happens even while the SA-1 is active;
; nvl_try_wake touches the live shadow only after observing arm=1 and a due epoch.
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
    plb
    lda #$80
    sta $2201            ; execute the coprocessor-IRQ enable (also migrates old checkpoints)
    lda $41012A
    inc a
    sta $41012A          ; one shared-window epoch increment per real SNES vblank
    jsr nvl_try_wake
    jsr nvl_sample_joy   ; prepare real-pad state for the next ordered release
    lda $3302            ; leave Bus-A latched on IRAM, not the NMI's ROM fetch
    plb
    rep #$30
    ply
    plx
    pla
    sep #$20
    lda $0002,s          ; own PHP byte is +1; hardware-saved return P is +2
    and #$FB             ; keep coprocessor IRQs enabled after NMI (also migrates old states)
    sta $0002,s
    plp
    rti

; SA-1 arm notification.  Clear the outbound request first, then either wake
; immediately when the two-vblank deadline is already due or return and let a
; later NMI do so.  Hardware IRQ entry has already masked nested IRQs.
.org $8F40
irq_vsync_wram_lab:
    php
    rep #$30
    pha
    phx
    phy
    phb
    sep #$20
    lda #$00
    pha
    plb
    lda #$80
    sta $2202            ; acknowledge SA-1 -> S-CPU coprocessor IRQ
    jsr nvl_try_wake
    jsr nvl_sample_joy   ; safe even if nvl_try_wake just resumed the SA-1
    lda $3302            ; leave Bus-A latched on IRAM
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
    sep #$20             ; R5 IRQ/NMI-WAKE LAB: handlers may preempt a long renderer
    lda #$80
    sta NMITIMEN         ; NMI on, auto-joypad remains off
    sta $2202            ; clear a stale SA-1 -> S-CPU request
    sta $2201            ; enable the SA-1 coprocessor IRQ source on the 5A22
    cli
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
            ".word $0000,$0000,irq,irq,$0000,nmi_vsync_lab,reset,irq_vsync_lab",
            "native-mode IRQ/NMI vectors",
        )
        interp_text = replace_once(
            interp_text,
            ".word $0000,$0000,irq,$0000,$0000,nmi,reset,irq",
            ".word $0000,$0000,irq,$0000,$0000,nmi_vsync_lab,reset,irq_vsync_lab",
            "emulation-mode IRQ/NMI vectors",
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
    if f".org ${LAB_HANDLER_ADDRESS:04X}" in esc5_text:
        raise RuntimeError("canonical escbank5 now owns the lab handler address")
    canonical_esc5 = (ROOT / "src/escbank5.bin").read_bytes()
    lab_offset = LAB_HANDLER_ADDRESS - 0x8000
    if len(canonical_esc5) > lab_offset:
        raise RuntimeError(
            "canonical escbank5 reaches the lab slot: "
            f"size ${len(canonical_esc5):04X}, slot offset ${lab_offset:04X}"
        )
    esc5_source = output_dir / "escbank5_vsync_lab.pasm"
    esc5_source.write_text(esc5_text + ESCBANK5_LAB, encoding="utf-8")

    video_text = (ROOT / "src/video.pasm").read_text(encoding="utf-8")
    if args.nmi_wake:
        video_text = replace_once(
            video_text, WL_SETUP_OLD, WL_SETUP_NMI, "enable 5A22 IRQ/NMI wake handlers"
        )
        video_text = replace_once(
            video_text,
            "    jsr joy5a22          ; refresh the JOY1 mailbox ($41:0000) once per game tick\n",
            "    nop                  ; R5VNMI03: NMI is the sole ordered mailbox producer\n"
            "    nop                  ; preserve vf_tick and every following address exactly\n"
            "    nop\n",
            "remove lagging foreground input producer",
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
    assemble(video_source, video_bin, output_dir / "video_vsync_lab.sym")

    interp = interp_bin.read_bytes()
    esc5 = esc5_bin.read_bytes()
    video = video_bin.read_bytes()
    if len(interp) != 0x8000:
        raise RuntimeError(f"lab interpreter is {len(interp)} bytes, expected 32768")
    if len(esc5) > 0x8000 or len(video) > 0x8000:
        raise RuntimeError("lab bank overflow")
    canonical_interp = (ROOT / "src/interp.bin").read_bytes()
    irq_trampoline_offset = IRQ_TRAMPOLINE_ADDRESS - 0x8000
    nmi_trampoline_offset = NMI_TRAMPOLINE_ADDRESS - 0x8000
    if args.nmi_wake:
        canonical_vector_slots = canonical_interp[
            irq_trampoline_offset : nmi_trampoline_offset + 4
        ]
        if canonical_vector_slots != bytes(8):
            raise RuntimeError(
                "canonical interpreter now owns the IRQ/NMI trampoline slots at "
                f"${IRQ_TRAMPOLINE_ADDRESS:04X}: {canonical_vector_slots.hex()}"
            )
    changed = [
        index for index, (before, after) in enumerate(zip(canonical_interp, interp))
        if before != after
    ]
    expected_main = set(range(0x7597, 0x75A3))
    allowed = set(expected_main)
    if args.nmi_wake:
        expected_vectors = set(
            range(irq_trampoline_offset, nmi_trampoline_offset + 4)
        )
        expected_vectors.update(
            (0x7FEA, 0x7FEB, 0x7FEE, 0x7FEF, 0x7FFA, 0x7FFB, 0x7FFE, 0x7FFF)
        )
        allowed.update(expected_vectors)
        if interp[
            irq_trampoline_offset : irq_trampoline_offset + 4
        ] != bytes.fromhex("5c408f7f"):
            raise RuntimeError(
                "IRQ lab trampoline bytes do not encode JML $7F8F40"
            )
        if interp[
            nmi_trampoline_offset : nmi_trampoline_offset + 4
        ] != bytes.fromhex("5c008f7f"):
            raise RuntimeError(
                "NMI lab trampoline bytes do not encode JML $7F8F00"
            )
        expected_nmi_vector = NMI_TRAMPOLINE_ADDRESS.to_bytes(2, "little")
        expected_irq_vector = IRQ_TRAMPOLINE_ADDRESS.to_bytes(2, "little")
        if (
            interp[0x7FEA:0x7FEC] != expected_nmi_vector
            or interp[0x7FFA:0x7FFC] != expected_nmi_vector
        ):
            raise RuntimeError("NMI lab vectors do not target the trampoline slot")
        if (
            interp[0x7FEE:0x7FF0] != expected_irq_vector
            or interp[0x7FFE:0x8000] != expected_irq_vector
        ):
            raise RuntimeError("IRQ lab vectors do not target the trampoline slot")
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
        rom[0xFFEA:0xFFEC] = NMI_TRAMPOLINE_ADDRESS.to_bytes(2, "little")
        rom[0xFFFA:0xFFFC] = NMI_TRAMPOLINE_ADDRESS.to_bytes(2, "little")
        rom[0xFFEE:0xFFF0] = IRQ_TRAMPOLINE_ADDRESS.to_bytes(2, "little")
        rom[0xFFFE:0x10000] = IRQ_TRAMPOLINE_ADDRESS.to_bytes(2, "little")
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
    detail = (
        f"$7597-$75A2 + asserted-zero ${NMI_TRAMPOLINE_ADDRESS:04X} "
        "NMI slot/vectors"
        if args.nmi_wake
        else "$7597-$75A2 only"
    )
    print(f"interp lab changes {detail}; $75A3 hook preserved")
    print(f"lab marker {marker.decode()} at file ${MARKER_OFFSET:06X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
