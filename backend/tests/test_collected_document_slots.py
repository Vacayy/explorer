import pytest

from pipeline.postgres_collected_documents_fixture import _slots

BASE = [(0, '2026-11-03'), (8, '2026-11-02'), (16, '2026-11-02'), (24, '2026-11-01')]


def test_items_take_their_time_slot_after_base_rows_of_the_same_time():
    values = _slots(BASE, [('new', '2026-11-04', 9), ('tie', '2026-11-02', 7), ('mid', '2026-11-01 12:00', 5),
                           ('old', '2026-10-01', 3), ('none', None, 1)], 8)
    order = sorted([*(value for value, _ in BASE), *values.values()])
    assert values['new'] < 0 and 16 < values['tie'] < values['mid'] < 24 < values['old'] < values['none']
    assert len(set(order)) == len(order)


def test_crowded_gap_is_spaced_evenly_and_full_gap_fails_closed():
    items = [(n, '2026-11-02 12:00', n) for n in range(7)]
    assert sorted(_slots(BASE, items, 8).values()) == list(range(1, 8))
    with pytest.raises(ValueError):
        _slots(BASE, [*items, (7, '2026-11-02 12:00', 7)], 8)


def test_same_time_items_keep_id_order_and_newest_first():
    values = _slots(BASE, [('b', '2026-11-05', 2), ('a', '2026-11-05', 1), ('c', '2026-11-06', 3)], 8)
    assert values['c'] < values['a'] < values['b'] < 0


def test_base_out_of_time_order_is_refused():
    with pytest.raises(ValueError):
        _slots([(0, '2026-11-01'), (8, '2026-11-02')], [('x', '2026-11-03', 1)], 8)
