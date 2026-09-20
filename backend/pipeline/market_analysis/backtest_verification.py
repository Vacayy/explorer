"""Independent accounting replay from exported opening/closing prices.

This verifier does not call the portfolio simulator or its indicator helpers.
It checks the stated accounting model, not the profitability of a strategy.
"""
from __future__ import annotations

import math

STRATEGY_IDS = {'buy_hold', 'sma_cross', 'breakout_20d', 'momentum_20d',
                'high52', 'high52_ihs', 'high52_ihs_ma'}


def _finite(value, *, positive=False):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and (value > 0 if positive else True))


def _same(a, b, message):
    if not _finite(a) or not _finite(b) or not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-5):
        raise ValueError(message)


def load_validation_input(folder, spec, result):
    """Trusted fixed query over Parquet, never a source database connection."""
    from .analytics import _connection, _input
    folder, manifest = _input(folder)
    codes = sorted({t['code'] for segment in result['segments'] for strategy in segment['strategies']
                    for rebalance in strategy['rebalances'] for t in rebalance['targets']}
                   | {t['code'] for segment in result['segments'] for strategy in segment['strategies']
                      for t in strategy['trades']})
    prices = {code: {} for code in codes}
    connection = _connection()
    try:
        cursor = connection.execute('''SELECT code,date,open,close,volume FROM read_parquet(?)
            WHERE date>=? AND date<=? AND code IN (SELECT unnest(?)) ORDER BY code,date''',
            [str(folder / 'daily.parquet'), spec['start_date'], spec['end_date'], codes])
        while batch := cursor.fetchmany(8192):
            for code, day, opening, close, volume in batch:
                prices[code][day] = {'open': opening, 'close': close, 'volume': volume}
    finally:
        connection.close()
    return prices, manifest['calendar']['dates']


def validate_result(result: dict, spec: dict, prices=None, calendar=None) -> None:
    if result.get('spec') != spec:
        raise ValueError('백테스트 결과의 조건이 고정된 요청과 다릅니다.')
    segments = result.get('segments', [])
    if [s.get('id') for s in segments] != ['development', 'holdout']:
        raise ValueError('개발·평가 구간이 누락되었습니다.')
    for segment in segments:
        start = spec['start_date'] if segment['id'] == 'development' else spec['split_date']
        end = spec['split_date'] if segment['id'] == 'development' else spec['end_date']
        in_period = lambda day: start <= day and (day < end if segment['id'] == 'development' else day <= end)
        expected_days = [d for d in calendar if in_period(d)] if calendar is not None else None
        if (not in_period(segment['start_date']) or not in_period(segment['end_date'])
                or segment['start_date'] >= segment['end_date']):
            raise ValueError('개발·평가 날짜가 요청 범위와 다릅니다.')
        if expected_days is not None and [segment['start_date'], segment['end_date']] != [expected_days[0], expected_days[-1]]:
            raise ValueError('평가 구간이 입력 스냅샷의 관측 거래일과 다릅니다.')
        strategies = segment['strategies']
        if len(strategies) != 7 or {s['id'] for s in strategies} != STRATEGY_IDS:
            raise ValueError('비교 전략이 누락되거나 중복되었습니다.')
        eligible = segment['universe']['codes']
        if len(eligible) != len(set(eligible)) or len(eligible) != segment['universe']['eligible']:
            raise ValueError('고정 유니버스 종목 수가 일치하지 않습니다.')
        for strategy in strategies:
            curve, trades = strategy['equity'], strategy['trades']
            days = [p['date'] for p in curve]
            if (len(days) < 2 or days != sorted(set(days))
                    or days[0] != segment['start_date'] or days[-1] != segment['end_date']
                    or (expected_days is not None and days != expected_days)):
                raise ValueError('평가 날짜가 올바르지 않습니다.')
            if [t['date'] for t in trades] != sorted(t['date'] for t in trades):
                raise ValueError('거래 원장이 시간 순서가 아닙니다.')
            index_by_day = {day: i for i, day in enumerate(days)}
            signal_days = days[::spec['rebalance_every']]
            if strategy['id'] == 'buy_hold':
                signal_days = signal_days[:1]
            if [r['signal_date'] for r in strategy['rebalances']] != signal_days:
                raise ValueError('재조정 일정이 고정 조건과 다릅니다.')
            for rebalance in strategy['rebalances']:
                signal = rebalance['signal_date']
                targets = rebalance['targets']
                if len({t['code'] for t in targets}) != len(targets) or len(targets) != rebalance['target_count']:
                    raise ValueError('목표 보유 목록이 중복되거나 집계와 다릅니다.')
                if strategy['id'] != 'buy_hold' and len(targets) > spec['max_positions']:
                    raise ValueError('최대 편입 수를 초과했습니다.')
                nav = curve[index_by_day[signal]]['nav']
                _same(nav, rebalance['signal_nav'], '신호일 평가액이 곡선과 다릅니다.')
                for target in targets:
                    if target['code'] not in eligible:
                        raise ValueError('고정 유니버스 밖 종목을 선택했습니다.')
                    slots = len(targets) if strategy['id'] == 'buy_hold' else spec['max_positions']
                    _same(target['weight'], 1/slots, '목표 비중이 공통 규칙과 다릅니다.')
                    if not _finite(target['signal_close'], positive=True):
                        raise ValueError('신호일 종가가 올바르지 않습니다.')
                    _same(target['quantity'], nav / slots / target['signal_close'], '목표 수량이 신호일 수치와 다릅니다.')
                    if prices is not None:
                        _same(target['signal_close'], prices[target['code']][signal]['close'], '신호일 종가가 입력과 다릅니다.')
            cash, peak, worst, total_cost = spec['initial_cash'], spec['initial_cash'], 0.0, 0.0
            holdings, marks = {}, {}
            cursor = stale_days = 0
            for point in curve:
                day = point['date']
                while cursor < len(trades) and trades[cursor]['date'] == day:
                    trade = trades[cursor]
                    if (trade['signal_date'] not in signal_days or trade['side'] not in {'buy', 'sell'}
                            or index_by_day[day] != index_by_day[trade['signal_date']] + 1
                            or trade['code'] not in eligible):
                        raise ValueError('신호 확정 다음 거래일 체결 규약을 위반했습니다.')
                    if (not all(_finite(trade[k], positive=True) for k in ('quantity', 'price', 'notional'))
                            or not _finite(trade['cost']) or trade['cost'] < 0):
                        raise ValueError('거래 수량·가격·비용의 부호 또는 유한성 오류입니다.')
                    code, quantity = trade['code'], trade['quantity']
                    if prices is not None:
                        bar = prices.get(code, {}).get(day, {})
                        if not _finite(bar.get('volume')) or bar['volume'] <= 0:
                            raise ValueError('거래가 없는 관측일에 체결했습니다.')
                        _same(trade['price'], bar.get('open'), '체결 시가가 입력 가격과 다릅니다.')
                    rate = spec['buy_cost_bps' if trade['side'] == 'buy' else 'sell_cost_bps']/10000
                    _same(quantity * trade['price'], trade['notional'], '체결 금액이 수량·가격과 다릅니다.')
                    _same(trade['notional'] * rate, trade['cost'], '체결 비용이 조건과 다릅니다.')
                    if trade['side'] == 'sell':
                        remaining = holdings.get(code, 0) - quantity
                        if remaining < -1e-8:
                            raise ValueError('보유 수량을 초과해서 매도했습니다.')
                        if remaining <= 1e-10:
                            holdings.pop(code, None)
                        else:
                            holdings[code] = remaining
                        cash += trade['notional'] - trade['cost']
                    else:
                        newly_held = code not in holdings
                        holdings[code] = holdings.get(code, 0) + quantity
                        if newly_held:
                            marks[code] = (trade['price'], day)
                        cash -= trade['notional'] + trade['cost']
                    total_cost += trade['cost']
                    _same(cash, trade['cash_after'], '거래 원장의 현금 수지가 일치하지 않습니다.')
                    if cash < -1e-5:
                        raise ValueError('차입 없는 실험에서 현금이 음수입니다.')
                    cursor += 1
                _same(cash, point['cash'], '일별 현금 수지가 일치하지 않습니다.')
                if not _finite(point['nav'], positive=True) or point['positions'] != len(holdings):
                    raise ValueError('일별 자산 금액 또는 보유 종목 수가 올바르지 않습니다.')
                if prices is not None:
                    stale = 0
                    for code in holdings:
                        close = prices.get(code, {}).get(day, {}).get('close')
                        if _finite(close, positive=True):
                            marks[code] = (close, day)
                        else:
                            stale += 1
                    stale_days += int(stale > 0)
                    value = math.fsum(q * marks[c][0] for c, q in holdings.items())
                    _same(point['nav'], cash+value, '일별 NAV가 스냅샷 종가·수량·현금과 다릅니다.')
                    _same(point['exposure_pct'], 100*value/(cash+value), '일별 주식 노출이 보유 평가액과 다릅니다.')
                    if point.get('stale_positions') != stale:
                        raise ValueError('지연 평가 보유 수가 입력 결측과 다릅니다.')
                peak = max(peak, point['nav'])
                drawdown = 100*(point['nav']/peak-1)
                worst = min(worst, drawdown)
                _same(point['drawdown_pct'], drawdown, '낙폭이 평가 곡선과 일치하지 않습니다.')
            if cursor != len(trades):
                raise ValueError('평가 구간 밖 거래가 남아 있습니다.')
            final = strategy['holdings']
            if len({h['code'] for h in final}) != len(final) or {h['code'] for h in final} != set(holdings):
                raise ValueError('종료 보유 목록이 거래 원장과 다릅니다.')
            for holding in final:
                code = holding['code']
                _same(holding['quantity'], holdings[code], '종료 수량이 거래 원장과 다릅니다.')
                if not _finite(holding['price'], positive=True):
                    raise ValueError('종료 보유 가격이 올바르지 않습니다.')
                _same(holding['value'], holding['quantity']*holding['price'], '종료 보유 평가액이 다릅니다.')
                if prices is not None:
                    _same(holding['price'], marks[code][0], '종료 보유 가격이 스냅샷과 다릅니다.')
                    if holding['valuation_date'] != marks[code][1]:
                        raise ValueError('종료 평가 날짜가 입력과 다릅니다.')
            _same(curve[-1]['nav'], cash+math.fsum(h['value'] for h in final), '종료 NAV가 현금과 보유 평가액의 합이 아닙니다.')
            metrics = strategy['metrics']
            _same(metrics['total_return_pct'], 100*(curve[-1]['nav']/spec['initial_cash']-1), '수익률이 평가액과 다릅니다.')
            _same(metrics['ending_nav'], curve[-1]['nav'], '종료 NAV 요약이 곡선과 다릅니다.')
            _same(metrics['max_drawdown_pct'], worst, '최대 낙폭이 곡선과 다릅니다.')
            _same(metrics['cost_total'], total_cost, '총 비용이 체결 원장과 다릅니다.')
            _same(metrics['exposure_avg_pct'], math.fsum(p['exposure_pct'] for p in curve)/len(curve), '평균 노출이 곡선과 다릅니다.')
            if metrics['trades_count'] != len(trades) or (prices is not None and metrics['stale_valuation_days'] != stale_days):
                raise ValueError('체결·지연 평가 집계가 원장과 다릅니다.')
