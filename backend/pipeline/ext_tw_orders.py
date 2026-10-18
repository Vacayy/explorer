"""대만 경제부 통계처 외판수주(外銷訂單) 월간 수집 (docs/specs/value-chain.md §7, LLM 0).

출처: 經濟部統計處 오픈데이터 CSV (data.gov.tw 데이터셋 6845·16361·16362가 가리키는 service.moea.gov.tw 파일).
  총액     b.csv                                  열: 統計項目,資料期(民國年),統計值(美元),計量單位(美元),統計值(新台幣),...
  품목별   經濟部統計處_外銷訂單_{품목}.csv         열: 統計項目,貨品別,資料期(民國年),統計值(金額),計量單位
資料期는 민국 연월 'YYYMM'(07301 = 1984-01). 1984-01부터 있다. 단위는 계량단위 열 '百萬美元'을 확인한다 — 다르면 오류.
주의: 오픈데이터 CSV는 보도자료(Bulletin.aspx?kind=5)보다 한 달쯤 늦게 갱신된다.
"""
from __future__ import annotations

import csv
import io
from urllib.parse import quote

import requests

from pipeline.ext_series import upsert

BASE = "https://service.moea.gov.tw/EE520/opendata/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
UNIT = "USD million"
SOURCE = "經濟部統計處 外銷訂單 opendata"
# 시리즈 → (파일명, 값 열 이름, 단위 열 이름)
FILES = {
    "tw_orders:total": ("b.csv", "統計值(美元)", "計量單位(美元)"),
    "tw_orders:ict": ("經濟部統計處_外銷訂單_資訊通訊產品.csv", "統計值(金額)", "計量單位"),
    "tw_orders:electronics": ("經濟部統計處_外銷訂單_電子產品.csv", "統計值(金額)", "計量單位"),
}


def parse_csv(text: str, value_col: str, unit_col: str) -> list[tuple[str, float]]:
    """CSV 본문 → [(YYYY-MM, 백만 달러)]. 빈 값·'-'는 건너뛴다"""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for col in ("資料期(民國年)", value_col, unit_col):
        if col not in (reader.fieldnames or []):
            raise ValueError(f"열 '{col}' 없음: {reader.fieldnames} — 레이아웃 변경 확인 필요")
    out: list[tuple[str, float]] = []
    for row in reader:
        unit = (row[unit_col] or "").strip()
        if unit != "百萬美元":
            raise ValueError(f"단위가 百萬美元이 아님: {unit!r}")
        raw = (row[value_col] or "").replace(",", "").strip()
        if raw in ("", "-", "…"):
            continue
        period = row["資料期(民國年)"].strip()
        if len(period) != 5 or not period.isdigit():
            raise ValueError(f"資料期 형식 이상: {period!r}")
        year, month = int(period[:3]) + 1911, int(period[3:])
        if not 1 <= month <= 12:
            raise ValueError(f"월 범위 이상: {period!r}")
        out.append((f"{year}-{month:02d}", float(raw)))
    return out


def collect() -> dict:
    import time

    from database import get_connection
    parsed: dict[str, tuple[str, list[tuple[str, float]]]] = {}
    errors: dict[str, str] = {}
    for key, (name, value_col, unit_col) in FILES.items():
        url = BASE + quote(name)
        try:
            res = requests.get(url, headers=UA, timeout=60)
            res.raise_for_status()
            rows = parse_csv(res.content.decode("utf-8-sig"), value_col, unit_col)
            if not rows:
                raise ValueError("행 0개")
            parsed[key] = (BASE + name, rows)
        except Exception as e:  # noqa: BLE001 — 수집 실패는 status로 드러낸다
            errors[key] = str(e)
        time.sleep(1)

    stored, series, latest = 0, [], {}
    if parsed:
        conn = get_connection()
        try:
            for key, (url, rows) in parsed.items():
                stored += upsert(conn, key, rows, UNIT, f"{SOURCE} ({url.rsplit('/', 1)[-1]})")
                series.append(key)
                latest[key] = max(rows)[0]
            conn.commit()
        finally:
            conn.close()
    missing = [k for k in FILES if k not in series]
    status = "error" if not series else ("partial" if missing else "ok")
    return {"stored": stored, "series": series, "latest": latest, "status": status, "unit": UNIT,
            **({"missing": missing} if missing else {}), **({"errors": errors} if errors else {})}
