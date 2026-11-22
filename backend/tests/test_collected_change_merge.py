from pipeline.postgres_collected_changes_fixture import _merge


def state(raw, summary, links):
    return {'raw': {'id': 1, **raw}, 'enrichments': [{'id': 5, 'doc_id': 1, 'summary': summary}],
            'links': [{'id': ident, 'doc_id': 1, 'entity_id': entity, 'link_type': 'mention', 'confidence': 1.0}
                      for ident, entity in links]}


def test_each_side_keeps_its_own_changes():
    before = state({'title': 't', 'fetched_at': 'a'}, 's', [(1, 7)])
    collected = state({'title': 'T2', 'fetched_at': 'a'}, 'S2', [(9, 8)])          # re-scraped and re-linked
    candidate = state({'title': 't', 'fetched_at': 'b'}, 's', [(1, 7), (-3, 6)])   # the candidate touched other parts
    merged, conflicts = _merge(before, collected, candidate)
    assert conflicts == []
    assert merged['raw'] == {'id': 1, 'title': 'T2', 'fetched_at': 'b'}
    assert merged['enrichments'][0]['summary'] == 'S2'
    assert [link['entity_id'] for link in merged['links']] == [6, 8]


def test_same_field_changed_differently_needs_review_and_keeps_the_candidate_value():
    before = state({'title': 't'}, 's', [])
    merged, conflicts = _merge(before, state({'title': 'collector'}, 's', []), state({'title': 'candidate'}, 's', []))
    assert conflicts == ['raw.title'] and merged['raw']['title'] == 'candidate'


def test_same_change_on_both_sides_is_not_a_conflict():
    before = state({'title': 't'}, 's', [])
    merged, conflicts = _merge(before, state({'title': 'x'}, 'y', []), state({'title': 'x'}, 'y', []))
    assert conflicts == [] and merged['raw']['title'] == 'x'


def test_revised_timeline_time_is_stored_as_the_first_publication_text():
    # 2026-11-22 images trial run 779: a revised timeline document failed on a datetime inside its JSON
    import json
    from datetime import datetime, timedelta, timezone
    from pipeline.postgres_collected_changes_fixture import _iso_utc
    kst = timezone(timedelta(hours=9))
    value = _iso_utc(datetime(2026, 11, 20, 12, 38, 40, tzinfo=kst))
    assert value == '2026-11-20T03:38:40+00:00'
    assert json.dumps({'published_at': value})
    assert _iso_utc('2026-11-20T03:38:40+00:00') == '2026-11-20T03:38:40+00:00'
