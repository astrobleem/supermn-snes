#!/usr/bin/env python3
"""Guard 5A22 NMI input and pending-DMA hardware ordering."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "video.pasm"
VIDEO_BIN = ROOT / "src" / "video.bin"


def block(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    finish = source.index(end, begin)
    return source[begin:finish]


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    nmi = block(source, "nmi_pacing_wram:", ".org $8F40")
    irq = block(source, "irq_pacing_wram:", "; ============")
    pending_dma = block(
        source, "service_pending_dma0:", "service_pending_dma0_end:"
    )
    keepalive = block(source, "nmi_video_keepalive:", "; ============")
    sample = block(source, "pacing_sample_joy:", "pacing_helpers_end:")
    publisher = block(
        source, "pacing_publish_vtime_joy:", "pacing_helpers_end:"
    )

    assert nmi.count("jsr pacing_sample_joy") == 1, (
        "NMI must retain the sole controller-sampling call"
    )
    assert "jsr pacing_sample_joy" not in irq, (
        "IRQ/NMI may not share the non-reentrant serial controller reader"
    )
    assert "pacing_vtime_publish_tail:\n    jmp pacing_publish_vtime_joy" in sample
    assert (
        publisher.index("sta $41015C          ; odd")
        < publisher.index("lda $1F12")
        < publisher.index("sta $41015E")
        < publisher.index("sta $41015C          ; even")
    ), "VTIME real-pad seqlock no longer publishes odd/sample/even"
    assert publisher.count("sta $410000") == 0 and "lda $410122" not in publisher, (
        "VTIME input staging must remain independent of the renderer mailbox/arm"
    )
    assert irq.count("    nop\n") == 3, (
        "retired IRQ sampler call must remain a size-neutral three-byte slot"
    )
    assert (
        nmi.index("jsr pacing_try_wake")
        < nmi.index("jsr service_pending_dma0")
        < nmi.index("jsr pacing_sample_joy")
    ), "NMI must retain scheduler-wake, pending-DMA, controller-sample order"
    assert nmi.count("    nop\n") == 8 and "$0008,s" not in nmi and "$0009,s" not in nmi, (
        "NMI must preserve both saved P bytes in its size-neutral eight-NOP slot"
    )
    assert (
        pending_dma.index("lda STAT78")
        < pending_dma.index("lda SLHV")
        < pending_dma.index("lda OPVCT")
    ), "pending DMA must reset OPVCT phase before latching and reading it"
    assert pending_dma.index("stz $1F11") < pending_dma.index("sta MDMAEN"), (
        "pending DMA must clear its flag before MDMAEN can admit a nested NMI"
    )
    assert (
        keepalive.index("lda $D0")
        < keepalive.index("pha")
        < keepalive.index("jsr bg_scroll")
        < keepalive.index("pla")
        < keepalive.index("sta $D0")
    ), "NMI scroll keepalive must preserve interrupted renderer $D0 scratch"

    image = VIDEO_BIN.read_bytes()
    # STAT78 resets the OPVCT alternating-byte selector; SLHV only latches the
    # counter.  Without this exact read order a high-first selector phase is
    # self-sustaining and can strand a foreground DMA descriptor forever.
    assert image[0x0A3D:0x0A46] == bytes.fromhex(
        "ad3f21ad3721ad3d21"
    ), "assembled pending-DMA counter sequence is not STAT78, SLHV, OPVCT"
    assert image[0x0A61:0x0A69] == bytes.fromhex("9c111fa9018d0b42"), (
        "assembled pending-DMA path does not clear its flag before MDMAEN"
    )
    # video.bin is assembled at $E9:8000, so runtime $7F:8F55 mirrors file
    # offset $0F55.  The old JSR $8E8A occupied exactly these three bytes.
    assert image[0x0F55:0x0F58] == b"\xEA\xEA\xEA", (
        "assembled IRQ sampler slot is not three NOPs"
    )
    # The source binary carries the VTIME-only tail and publisher.  Ordinary
    # ROM packing restores the historical RTS/zero gap; the dedicated pack
    # regression checks both modes.
    assert image[0x0EA8:0x0EAB] == bytes.fromhex("4cab8e"), (
        "assembled controller sampler no longer tails into VTIME staging"
    )
    # Preserve the interrupted I state instead of opening an IRQ window before
    # NMI RTI or enabling a nested IRQ inside a preempted IRQ handler.
    assert image[0x0F2B:0x0F33] == b"\xEA" * 8, (
        "assembled NMI saved-status slot is not eight NOPs"
    )
    assert image[0x0F80:0x0F96] == bytes.fromhex(
        "20008bad0233f00dc220a5d04820b0a16885d0e22060"
    ), "assembled NMI scroll keepalive does not preserve $D0"
    print("5A22 pacing input/DMA order regression: PASS")


if __name__ == "__main__":
    main()
