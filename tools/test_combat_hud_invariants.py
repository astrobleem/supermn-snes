#!/usr/bin/env python3
"""Static guards for combat BG provenance and the centered two-player HUD."""

from pathlib import Path

import validate_fast_obj_renderer
import validate_paced_obj_sources
import validate_packed_obj_snapshot


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "escbank8.pasm"


def block(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    finish = text.index(end, begin)
    return text[begin:finish]


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")

    # Generic producer notifications must not destroy a token merely because
    # a transient write occurred; exact comparison owns that decision.
    for name, end in (
        ("shadow_dirty_publish:", "shadow_dirty_publish_end:"),
        ("mark_bg_dirty:", "mark_bg_dirty_end:"),
    ):
        writer = block(text, name, end)
        assert "$41014A" not in writer
        assert "$014A" not in writer

    full = block(text, "rmb_bg_full_scan:", "rmb_bg_first:")
    assert "jsr rmb_bg_changed_publish" in full
    first = block(text, "rmb_bg_first:", "rmb_bg_clean:")
    assert "jsr rmb_bg_invalidate_tokens" not in first
    assert "jmp rmb_bg_first_finish" in first

    first_finish = block(
        text, "rmb_bg_first_finish:", "rmb_bg_first_finish_end:"
    )
    assert "lda $014A" in first_finish
    assert "cmp #$C0BC" in first_finish
    assert "jsr rmb_bg_invalidate_tokens" in first_finish
    assert "jsr rmb_prepare_bg" in first_finish
    assert first_finish.index("cmp #$C0BC") < first_finish.index(
        "jsr rmb_bg_invalidate_tokens"
    )

    sparse = block(text, "render_bg_dirty_sparse:", "render_bg_dirty_sparse_end:")
    assert "$015A" not in sparse
    assert sparse.count("$0160") == 4
    assert "jsr rmb_bg_changed_publish" in sparse

    top = block(text, "rox_top_right:", "rox_top_fallback:")
    assert "sbc #$0030" in top
    assert "sbc #$0018" not in top

    helper = block(text, "rmb_bg_changed_publish:", "escbank8_physical_end:")
    assert "sta $41013A" in helper
    changed = block(
        text, "rmb_bg_changed_publish:", "rmb_bg_changed_publish_done:"
    )
    assert "jsr rmb_bg_validate_tokens" in changed
    assert "jsr rmb_bg_invalidate_tokens" not in changed
    invalidator = block(text, "rmb_bg_invalidate_tokens:", "rmb_bg_changed_publish:")
    assert "stz $014A" in invalidator and "stz $015A" in invalidator

    validator = block(
        text, "rmb_bg_validate_tokens:", "rmb_bg_validate_tokens_end:"
    )
    assert "cmp #$C0BC" in validator
    assert "lda $414800,x" in validator and "cmp $A000,x" in validator
    assert "lda $414C00,x" in validator and "cmp $A400,x" in validator
    assert "jmp rmb_bg_invalidate_tokens" in validator

    publisher = block(
        text, "hc0bc_hle_after_29b6:", "hc0bc_hle_after_end:"
    )
    assert "jsr hc0bc_token_snapshot" in publisher
    snapshot = block(
        text, "hc0bc_token_snapshot:", "hc0bc_token_snapshot_end:"
    )
    assert snapshot.count("mvn $41,$41") == 2
    for literal in ("#$4800", "#$4C00", "#$A000", "#$A400"):
        assert literal in snapshot

    # All three Python mirrors must agree with the producer at P2's raw
    # top-row origins, including the complete 24-pixel leftward shift.
    mirrors = (
        validate_fast_obj_renderer.packed_x_word,
        validate_paced_obj_sources.packed_x_word,
        validate_packed_obj_snapshot.packed_x_word,
    )
    for mirror in mirrors:
        for raw_x in (0x0120, 0x0130, 0x0140, 0x0160):
            assert mirror(0x00E2, raw_x, 0x0001) == raw_x - 0x0030
        assert mirror(0x00E2, 0x0100, 0x0001) == 0x0100

    # The helper occupies the exact 19-byte DE6D-DE7F seam before DE80.
    assert ".org $DE6D" in text
    seam = block(text, ".org $DE6D", ".org $DE80")
    assert seam.index("rmb_bg_invalidate_tokens:") < seam.index(
        "rmb_bg_changed_publish:"
    )
    assert ".org $EF80" not in text
    print("combat/HUD static invariants: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
