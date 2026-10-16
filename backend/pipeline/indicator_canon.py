"""지표 정본 — 한 지표를 한 계열에서만 읽는다.

금리 2Y·10Y·VIX·공포탐욕은 매크로(macro_*)·시장 국면(vix·fear_greed)·Risk(risk_*) 수집기가 각자 저장해
같은 날 값이 갈렸다(^TNX 장중값 vs FRED DGS10, CNN 잠정값 vs 확정값). 정본은 pipeline.risk가 적재하는
risk_* 계열이다: 금리=FRED 공식 계열(공표 1영업일 지연), VIX=Yahoo ^VIX, 공포탐욕=CNN graphdata
(미래·당일 잠정 관측 제외). 다른 수집기는 이 계열을 읽고 갱신은 refresh()로 위임한다. 레거시 행은 지우지 않는다.
"""
CANONICAL = {"us2y": "risk_us2y", "us10y": "risk_us10y", "vix": "risk_vix", "fear_greed": "risk_fear_greed"}


def refresh(keys: tuple[str, ...]) -> list[str]:
    """정본 계열을 Risk 수집기로 갱신한다(6시간 캐시 존중). 실패한 키를 'key(ErrorType)'로 돌려준다."""
    from pipeline.risk import _snapshot_one   # risk가 macro·market_regime을 import하므로 지연 import
    failed = []
    for key in keys:
        result = _snapshot_one(key)
        if result["status"] == "error":
            failed.append(f"{key}({result.get('error')})")
    return failed
