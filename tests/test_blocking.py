"""Deterministic candidate block and cap behavior."""

from dedup.blocking import block_keys, build_blocks


def rec(identifier, **values):
    return {"source_record_id": identifier, **values}


def test_pairs_are_canonical_deduplicated_and_shuffle_stable():
    rows = [rec("b", email_norm="same@test.com", phone_norm="123"),
            rec("a", email_norm="same@test.com", phone_norm="123"),
            rec("c", email_norm="same@test.com")]
    pairs, stats = build_blocks(rows, 10)
    assert pairs == [("a", "b"), ("a", "c"), ("b", "c")]
    assert build_blocks(list(reversed(rows)), 10) == (pairs, stats)


def test_missing_email_can_pair_by_phone_or_composite_key():
    phone_rows = [rec("a", phone_norm="555"), rec("b", phone_norm="555")]
    composite_rows = [rec("c", name_norm="jane doe", soundex_last="D000", postcode_norm="123456"),
                      rec("d", name_norm="john doe", soundex_last="D000", postcode_norm="123456")]
    assert build_blocks(phone_rows, 10)[0] == [("a", "b")]
    assert block_keys(composite_rows[0]) == [("soundex_first_postcode", "D000|j|123456")]
    assert build_blocks(composite_rows, 10)[0] == [("c", "d")]


def test_oversized_blocks_report_skipped_pairs_and_reduction():
    rows = [rec(str(index), email_norm="crowded@test.com") for index in range(4)]
    pairs, stats = build_blocks(rows, 3)
    assert pairs == []
    assert stats.capped_block_count == 1
    assert stats.pairs_skipped_cap == 6
    assert stats.capped_blocks[0].size == 4
    assert stats.capped_blocks[0].pairs_skipped == 6

    small = [rec("a", email_norm="one@test.com"), rec("b", email_norm="one@test.com"), rec("c")]
    _, simple_stats = build_blocks(small, 10)
    assert simple_stats.comparisons_naive == 3
    assert simple_stats.comparisons_blocked == 1
    assert abs(simple_stats.reduction_ratio - 2 / 3) < 1e-12


def test_generated_scale_records_do_not_create_quadratic_candidates():
    rows = [rec(f"record-{index:04d}", email_norm=f"person-{index}@example.test")
            for index in range(3000)]
    pairs, stats = build_blocks(rows, 200)
    assert pairs == []
    assert stats.comparisons_naive == 3000 * 2999 // 2
    assert stats.comparisons_blocked == 0

