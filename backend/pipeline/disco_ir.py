"""디스코(6146) 분기 매출·수주 — IR 엑셀 'Quarterly' 시트 (밸류체인 다이싱·그라인딩 장비 칸, docs/specs/value-chain.md §13, LLM 0).

일본 회사별 분기 실적은 키 없는 기계 판독 원천이 거의 없다(EDINET은 키 필요 — 사용자 보류). 디스코만 IR 페이지에
분기 엑셀(연결 매출 FY2000~, 수주·출하·매출·수주잔고 FY2011~)을 올린다. 파일명은 결산 발표일(fr{YYYYMMDD}.xlsx)이라
목록 페이지에서 최신 링크를 긁는다.
- 회계연도는 4월 시작: FYn 1Q = n년 4~6월 → 달력 분기 'n-06', 4Q = n+1년 1~3월 → '(n+1)-03'.
- 단위 백만 엔 → 고정 환율 1/150로 USD(YoY는 엔화 YoY와 같다 — 환율 변동을 섞지 않음). 표 머리말 단위가 바뀌면 오류.
저장: us_quarterly(ticker DISCO, metric revenue → use_key jp_backend).
수주(Order 행)는 FY2021(2022-03)을 끝으로 공시가 중단돼 쓰지 않는다 — 끊긴 수주를 최신처럼 보이지 않게.
"""
from __future__ import annotations

import io
import re

import openpyxl
import requests

LIST_URL = "https://www.disco.co.jp/jp/ir/library/fr.html"
FILE_URL = "https://www.disco.co.jp/jp/ir/library/doc/fr/{name}"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
TICKER = "DISCO"
JPY_USD = 1 / 150
ROWS = {"revenue": ("Net Sales", "jp_backend")}


def _qkey(fy: int, qn: int) -> str:
    m = qn * 3 + 3
    return f"{fy + 1}-03" if m > 12 else f"{fy}-{m:02d}"


def parse_workbook(data: bytes) -> dict[str, dict[str, float]]:
    """엑셀 → {metric: {달력 분기: 백만 엔}}. 연결 매출은 첫 'Net Sales' 행"""
    ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)["Quarterly"]
    rows = list(ws.iter_rows(values_only=True))
    if not rows or "Millions of Yen" not in str(rows[0][1] or ""):
        raise ValueError("Quarterly 시트 단위 머리말('Millions of Yen')을 찾지 못함 — 레이아웃 변경 확인 필요")
    fy_cols, fy = {}, None
    for i, v in enumerate(rows[0]):
        if isinstance(v, str) and (m := re.fullmatch(r"FY(\d{4})", v.strip())):
            fy = int(m.group(1))
        if fy is not None and i >= 2:
            q = rows[1][i]
            if isinstance(q, str) and re.fullmatch(r"[1-4]Q", q.strip()):
                fy_cols[i] = (fy, int(q.strip()[0]))
    out: dict[str, dict[str, float]] = {}
    for metric, (label, _) in ROWS.items():
        row = next((r for r in rows if r and str(r[1] or "").strip() == label), None)
        if row is None:
            raise ValueError(f"'{label}' 행을 찾지 못함 — 레이아웃 변경 확인 필요")
        out[metric] = {_qkey(*fq): float(row[i]) for i, fq in fy_cols.items() if isinstance(row[i], (int, float))}
    return out


def collect() -> dict:
    from database import get_connection
    html = requests.get(LIST_URL, headers=UA, timeout=30).text
    names = sorted(set(re.findall(r"fr\d{8}\.xlsx", html)))
    if not names:
        return {"status": "error", "stored": 0, "error": "디스코 IR 목록에서 분기 엑셀 링크를 찾지 못함"}
    r = requests.get(FILE_URL.format(name=names[-1]), headers=UA, timeout=60)
    r.raise_for_status()
    data = parse_workbook(r.content)
    conn = get_connection()
    stored = 0
    try:
        for metric, qs in data.items():
            use = ROWS[metric][1]
            for q, v in qs.items():
                conn.execute("INSERT INTO us_quarterly (ticker, q, metric, value, tag, use_key, fetched_at) VALUES (?,?,?,?,?,?, datetime('now')) "
                             "ON CONFLICT(ticker, q, metric) DO UPDATE SET value=excluded.value, tag=excluded.tag, use_key=excluded.use_key, "
                             "fetched_at=excluded.fetched_at",
                             (TICKER, q, metric, v * 1e6 * JPY_USD, f"disco-ir:{names[-1]}(JPY×1/150)", use))
                stored += 1
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok" if stored else "error", "stored": stored, "file": names[-1],
            "latest": max(data["revenue"]) if data["revenue"] else None}
