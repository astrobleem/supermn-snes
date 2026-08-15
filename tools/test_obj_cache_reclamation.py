#!/usr/bin/env python3
"""Focused contract tests for displayed OBJ-cache ownership retention."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO = (ROOT / "src" / "video.pasm").read_text(encoding="utf-8")


def reclaim(
    displayed_slots: list[int],
    reverse_codes: dict[int, int],
    current_pairs: list[tuple[int, int]],
) -> tuple[dict[int, int], list[int]]:
    """Model the assembly's first-owner-wins retained-pair rebuild."""

    used: set[int] = set()
    retained: list[tuple[int, int]] = []
    for slot in displayed_slots:
        if slot in used:
            continue
        used.add(slot)
        code = reverse_codes.get(slot, 0) & 0x3FFF
        if code:
            retained.append((code, slot))
    for code, slot in current_pairs:
        if slot in used:
            continue
        used.add(slot)
        retained.append((code & 0x3FFF, slot))

    assert len(retained) <= 128
    rebuilt: dict[int, int] = {}
    for code, slot in retained:
        rebuilt.setdefault(code, slot)
    free = [slot for slot in range(128) if slot not in used]
    return rebuilt, free


def test_displayed_common_codes_survive_repeated_reclamation() -> None:
    common_codes = list(range(0x10, 0x20))
    reverse = {slot: code for slot, code in enumerate(common_codes)}
    current = [(0x2400 + index, 32 + index) for index in range(33)]

    first, _free = reclaim(list(range(16)), reverse, current)
    assert all(first[code] == slot for slot, code in enumerate(common_codes))

    # A later scene still resolves every common displayed record as a cache hit;
    # it cannot reproduce the measured 16-code reload burst.
    reverse2 = {slot: code for code, slot in first.items()}
    second, _free = reclaim(list(range(16)), reverse2, current[4:])
    assert all(second[code] == slot for slot, code in enumerate(common_codes))


def test_displayed_owner_wins_duplicate_code_without_reusing_either_slot() -> None:
    # A new candidate can already have the same code in another physical slot.
    # Rehash must terminate, keep the displayed owner addressable, and quarantine
    # both slots until a later generation makes either one genuinely unused.
    rebuilt, free = reclaim([7], {7: 0x1234}, [(0x1234, 42)])
    assert rebuilt == {0x1234: 7}
    assert 7 not in free and 42 not in free


def test_source_contract() -> None:
    stub = VIDEO[
        VIDEO.index("obj_cache_protect_displayed:"):
        VIDEO.index("obj_cache_protect_displayed_end:")
    ]
    extended = VIDEO[
        VIDEO.index("obj_cache_protect_displayed_extended:"):
        VIDEO.index("obj_cache_protect_displayed_extended_end:")
    ]
    queue_tail = VIDEO[
        VIDEO.index("obj_tile_queue:"):VIDEO.index("obj_cache_full:")
    ]
    batch_lead = VIDEO[
        VIDEO.index("nmi_batch_present_then_wake:"):
        VIDEO.index("nmi_batch_present_then_wake_end:")
    ]

    assert "jml.l obj_cache_protect_displayed_extended|$E90000" in stub
    assert "sta $7E2E00,x" in extended
    assert "lda $7E4A00,x" in extended
    assert "sta $7E2D00,x" in extended
    assert "sta $7E2F00,x" in extended
    assert "cmp #$0080\n    bcs ocpde_overflow" in extended
    assert "cmp $C4\n    bne ocpde_code_next\n    jmp ocpde_next16" in extended
    assert "lda $7E5800,x" in extended
    assert "jml.l obj_tile_queue_publish_reverse|$E90000" in queue_tail
    assert batch_lead.index(
        "jsl.l nmi_batch_present_arbitrate|$E90000"
    ) < batch_lead.index(
        "jsl.l nmi_obj_tile_batch_dispatch|$E90000"
    )


def main() -> None:
    test_displayed_common_codes_survive_repeated_reclamation()
    test_displayed_owner_wins_duplicate_code_without_reusing_either_slot()
    test_source_contract()
    print("obj cache reclamation tests: PASS")


if __name__ == "__main__":
    main()
