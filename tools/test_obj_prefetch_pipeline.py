#!/usr/bin/env python3
"""Focused fail-closed contracts for the early immutable OBJ upload plan."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO = (ROOT / "src" / "video.pasm").read_text(encoding="utf-8")


def conservative_plan(record_count: int, available_slots: int) -> bool:
    """Match the assembly's no-partial-plan capacity decision."""

    if not 0 <= record_count <= 128:
        raise ValueError("manifest record count outside the OAM bound")
    if not 0 <= available_slots <= 128:
        raise ValueError("available slot count outside the cache bound")
    return record_count <= available_slots


def test_target_burst_is_eligible_without_guessing_uniqueness() -> None:
    # The exact predecessor had 70 available slots and 16 genuine first-use
    # records.  The planner accepts even the conservative one-slot-per-record
    # bound; it does not need a game-specific tile catalog.
    assert conservative_plan(16, 70)


def test_capacity_failure_is_all_or_nothing() -> None:
    assert not conservative_plan(71, 70)


def test_packed_empty_is_terminal() -> None:
    # $8000 is the producer's valid packed-empty marker, not a pointer to the
    # first record.  Reading BC02 for this case caused the failed 4d897347 boot
    # candidate to fill/reset the cache forever before its first render.
    assert conservative_plan(0, 128)


def complete_group_span(slots: list[int]) -> tuple[int, int] | None:
    """Coalesce only queues that exactly cover aligned physical groups."""

    if not slots or len(slots) > 16:
        return None
    if any(slot != slots[0] - index for index, slot in enumerate(slots)):
        return None
    if len(slots) % 8 or slots[-1] % 8 != 0 or slots[0] % 8 != 7:
        return None
    first_group = slots[-1] // 8
    last_group = slots[0] // 8
    count = last_group - first_group + 1
    return (first_group, count) if count <= 3 else None


def test_partial_edge_burst_never_widens_into_displayed_slots() -> None:
    # The rejected da1fa538 path widened queued slots 72..66 to groups 64..79,
    # overwriting still-displayed Superman slots 73..79.
    assert complete_group_span(list(range(72, 65, -1))) is None
    assert complete_group_span(list(range(85, 69, -1))) is None


def test_exact_aligned_groups_coalesce() -> None:
    assert complete_group_span(list(range(87, 71, -1))) == (9, 2)


def test_irregular_slots_fail_closed() -> None:
    assert complete_group_span([85, 84, 82]) is None


def test_source_contract() -> None:
    frame = VIDEO[VIDEO.index("vid_frame:") : VIDEO.index("decode_tile:")]
    planner = VIDEO[
        VIDEO.index("obj_prefetch_begin:") : VIDEO.index("obj_prefetch_begin_end:")
    ]
    prepare = VIDEO[
        VIDEO.index("obj_fast_prepare_prefetched:") :
        VIDEO.index("obj_fast_prepare_prefetched_end:")
    ]
    finish = VIDEO[
        VIDEO.index("obj_upload_queued_extended:") :
        VIDEO.index("obj_upload_queued_extended_end:")
    ]
    dispatch = VIDEO[
        VIDEO.index("nmi_obj_tile_batch_dispatch:") :
        VIDEO.index("nmi_obj_tile_batch_dispatch_end:")
    ]
    staged = VIDEO[
        VIDEO.index("nmi_obj_tile_batch_staged:") :
        VIDEO.index("nmi_obj_tile_batch_staged_end:")
    ]
    copier = VIDEO[
        VIDEO.index("obj_prefetch_stage_records:") :
        VIDEO.index("obj_prefetch_stage_records_end:")
    ]
    group_batch = VIDEO[
        VIDEO.index("nmi_obj_tile_batch_group:") :
        VIDEO.index("nmi_obj_tile_batch_group_end:")
    ]
    dma0_target = VIDEO[
        VIDEO.index("dma0_restore_map_vmaddr:") :
        VIDEO.index("dma0_restore_map_vmaddr_end:")
    ]
    group_stage = VIDEO[
        VIDEO.index("obj_prefetch_stage_groups_try:") :
        VIDEO.index("obj_prefetch_stage_groups_try_end:")
    ]

    assert frame.index("jsl.l obj_prefetch_begin|$E90000") < frame.index("jsr vid_bg")
    assert "jsr obj_fast_prepare" in planner
    assert "cmp #$8000           ; packed-empty is a complete zero-record manifest" in planner
    assert "bne opb_manifest_has_records\n    jmp opb_publish" in planner
    assert (
        "opb_manifest_has_records:\n"
        "    bcs opb_packed_capacity"
    ) in planner
    assert "opb_manifest_has_records:\n    bmi opb_packed_capacity" not in planner
    assert planner.rindex("sta $7E74AC") < planner.index("sta $7E74A2")
    assert "cmp #$0011" in planner
    assert "jsr obj_prefetch_stage_groups_try" in planner
    assert "jsr obj_prefetch_stage_records" in planner
    assert "cmp $D0\n    bcc opb_legacy_begin\n    beq opb_legacy_begin" in planner
    assert "bcs opb_packed_begin\n    jmp opb_decline" in planner
    assert "lda $1F20\n    beq ofpp_fallback" in prepare
    assert "lda $1F20\n    bne ouqe_wait" in finish
    assert finish.rindex("sta $7E74AC") < finish.index("jml.l ouq_done|$7F0000")
    assert "jml.l obj_upload_queued_extended|$E90000" in VIDEO
    assert "cmp #$A55A" in dispatch
    assert "cmp #$A55B" in dispatch
    assert "jml.l nmi_obj_tile_batch_group|$E90000" in dispatch
    assert "jml.l nmi_obj_tile_batch_staged|$E90000" in dispatch
    assert "lda #$007E\n    sta $D2" in staged
    assert "adc #OBJ_PREFETCH_STAGE" in staged
    assert staged.count("sta MDMAEN") == 2
    assert "sta WMADDL" in copier and "sta WMADDM" in copier
    assert "stz WMADDH" in copier and "sta BBAD5" in copier
    assert "adc #OBJ_PREFETCH_STAGE" in copier
    assert "lda #$80\n    sta DAS5L" in copier
    assert copier.count("sta MDMAEN") == 1
    assert "lda $7E4A00,x" in group_stage
    assert group_stage.count("and #$0007") >= 3
    assert "beq opsg_count_aligned\n    jmp opsg_fail" in group_stage
    assert "beq opsg_low_aligned\n    jmp opsg_fail" in group_stage
    assert "beq opsg_high_aligned\n    jmp opsg_fail" in group_stage
    assert "jmp opsg_fail        ; never rewrite an unowned retained/displayed slot" in group_stage
    assert "sta $7E74AE" in group_stage
    assert "lda #OBJ_PREFETCH_STAGE" in group_stage
    assert group_stage.count("sta MDMAEN") == 1
    assert "adc #OBJ_PREFETCH_STAGE" in group_batch
    assert "lda #$0400\n    sta $D6" in group_batch
    assert "lda #$7E\n    sta A1B5" in group_batch
    assert group_batch.count("sta MDMAEN") == 1
    assert "sta $7E74A0          ; expose record completion only after the final group" in group_batch
    assert "jsl.l dma0_restore_map_vmaddr|$E90000" in VIDEO
    assert "lda $7E72B9" in dma0_target
    assert "cmp #$A5" in dma0_target
    assert "stz VMADDL" in dma0_target and "stz VMADDH" in dma0_target
    assert "$7E:C000-$CBFF" in VIDEO


def main() -> None:
    test_target_burst_is_eligible_without_guessing_uniqueness()
    test_capacity_failure_is_all_or_nothing()
    test_packed_empty_is_terminal()
    test_partial_edge_burst_never_widens_into_displayed_slots()
    test_exact_aligned_groups_coalesce()
    test_irregular_slots_fail_closed()
    test_source_contract()
    print("OBJ prefetch pipeline tests: PASS")


if __name__ == "__main__":
    main()
