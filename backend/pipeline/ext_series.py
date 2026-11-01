"""외부 월간 시계열 저장 계약 (docs/specs/value-chain.md §7) — 수집기들이 공유한다 (LLM 0).

수집기 하나 = 모듈 하나(`pipeline/ext_<출처>.py`)이고 `collect() -> {"stored": n, "series": [...], "status": ok|partial|error, ...}`를 낸다.
저장은 `upsert(conn, series, rows, unit, source)`, 읽기는 `read(conn, series)`. period는 'YYYY-MM'.
"""
from __future__ import annotations


def upsert(conn, series: str, rows: list[tuple[str, float]], unit: str, source: str) -> int:
    """rows = [(YYYY-MM, 값)]. 같은 (series, period)는 덮어쓴다"""
    for period, value in rows:
        if value is None:
            continue
        conn.execute("INSERT INTO ext_series (series, period, value, unit, source, fetched_at) VALUES (?,?,?,?,?, datetime('now')) "
                     "ON CONFLICT(series, period) DO UPDATE SET value=excluded.value, unit=excluded.unit, source=excluded.source, "
                     "fetched_at=excluded.fetched_at", (series, period, float(value), unit, source))
    return len(rows)


def read(conn, series: str) -> dict[str, float]:
    return {r["period"]: r["value"] for r in conn.execute(
        "SELECT period, value FROM ext_series WHERE series=? ORDER BY period", (series,))}


def yoy3m(series: dict[str, float]) -> dict[str, float]:
    """월간 값 → 3개월 합의 전년 대비(%) — 3개월과 전년 3개월이 모두 있을 때"""
    out = {}
    for p in sorted(series):
        y, m = int(p[:4]), int(p[5:])
        months = [f"{(y * 12 + m - 1 - k) // 12}-{(y * 12 + m - 1 - k) % 12 + 1:02d}" for k in range(3)]
        prev = [f"{int(x[:4]) - 1}{x[4:]}" for x in months]
        if all(x in series for x in months + prev) and sum(series[x] for x in prev):
            out[p] = (sum(series[x] for x in months) / sum(series[x] for x in prev) - 1) * 100
    return out
