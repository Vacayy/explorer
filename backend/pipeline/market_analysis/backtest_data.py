"""Load only a hash-checked exported snapshot inside the analysis sandbox."""
from pathlib import Path

if __package__:
    from .analytics import _connection, _input, _series
else:
    from analytics import _connection, _input, _series


def calculate_snapshot(data_dir: str | Path, spec: dict) -> dict:
    if __package__:
        from .backtest_engine import compute_backtest
    else:
        from backtest_engine import compute_backtest

    folder, manifest = _input(data_dir)
    if spec['end_date'] > manifest['as_of']:
        raise ValueError('종료일 이후까지 수집된 입력 스냅샷이 필요합니다.')
    calendar = [d for d in manifest['calendar']['dates'] if d <= spec['end_date']]
    if calendar != sorted(set(calendar)):
        raise ValueError('스냅샷 거래일 목록이 올바르지 않습니다.')
    for start, end in ((spec['start_date'], spec['split_date']),
                       (spec['split_date'], None)):
        dates = [d for d in calendar if d >= start and (end is None or d < end)]
        if len(dates) < 2:
            raise ValueError('개발·평가 구간마다 최소 2개 관측 거래일이 필요합니다.')
    connection = _connection()
    try:
        raw = connection.execute('SELECT code,name,market FROM read_parquet(?) ORDER BY code',
                                 [str(folder / 'universe.parquet')]).fetchall()
        universe = [dict(zip(('code', 'name', 'market'), row)) for row in raw]
        prices = dict(_series(connection, folder, spec['end_date']))
        for rows in prices.values():
            if any(a['date'] >= b['date'] for a, b in zip(rows, rows[1:])):
                raise ValueError('동일 종목의 시세 날짜가 중복되거나 역순입니다.')
    finally:
        connection.close()
    result = compute_backtest(prices, universe, calendar, spec)
    result['warnings'] = list(dict.fromkeys([
        *manifest.get('warnings', []), *result.get('warnings', []),
        '현재 보유 종목과 현재 시장 분류를 사용합니다. 과거 상장·상장폐지 이력이 없어 생존 편향을 제거하지 못했습니다.',
        'NAVER 수정주가의 가상 수량으로 계산합니다. 배당 포함 총수익률 및 과거 기업행동별 실제 수량을 보증하지 않습니다.',
        '시가 체결과 예시 비용을 가정한 연구 결과입니다. 호가·거래정지·가격 제한·유동성에 따른 실제 체결을 완전히 재현하지 않습니다.',
        '개발·평가 구간의 결과를 함께 공개합니다. 재실행으로 평가 구간을 반복 확인하면 더 이상 미관측 검증 표본이 아닙니다.',
    ]))
    result['snapshot'] = {k: manifest[k] for k in ('snapshot_id', 'as_of', 'rows', 'symbols',
                                                   'price_adjustment', 'files')}
    return result
