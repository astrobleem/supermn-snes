#!/usr/bin/env python3
"""Regression tests for fresh-power OBJ queue snapshot decoding."""

import capture_mesen211_transitions as capture


def main() -> None:
    count, valid = capture.bounded_obj_queue_count(9126, 0x0000)
    assert (count, valid) == (0, False)

    count, valid = capture.bounded_obj_queue_count(128, 0xA55A)
    assert (count, valid) == (128, True)

    try:
        capture.bounded_obj_queue_count(129, 0xA55A)
    except RuntimeError as error:
        assert "exceeds hardware bound" in str(error)
    else:
        raise AssertionError("initialized queue overflow must fail closed")

    print("fresh-power OBJ queue snapshot guard: green")


if __name__ == "__main__":
    main()
