"""미국 Census C30 건설지출 — 민간 'Data center' 열 수집 (docs/specs/value-chain.md §7, LLM 0).

출처 두 파일(같은 레이아웃, 4행 머리말·A열 'Mon-YY'(+p 잠정/r 수정)·최신월이 위):
- privtime.xlsx   : 원계열(NSA) 월간 지출, 백만 달러 → 'census:datacenter' (전년 동월 비교용, 우선)
- privsatime.xlsx : 계절조정 연율(SAAR), 백만 달러 → 'census:datacenter_saar' (수준 비교용)
'Data center'는 Office 하위 항목이고 2014-01부터 값이 있다(그 전은 빈칸).
"""
from __future__ import annotations

import io
import re

import openpyxl
import requests

from pipeline.ext_series import upsert

BASE = "https://www.census.gov/construction/c30/xlsx/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
SOURCE = "US Census C30 Construction Spending"
FILES = [  # (파일, series, unit)
    ("privtime.xlsx", "census:datacenter", "USD mn (NSA, monthly)"),
    ("privsatime.xlsx", "census:datacenter_saar", "USD mn (SAAR)"),
]
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun",
                                    "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_DATE = re.compile(r"^([A-Za-z]{3})-(\d{2})[pr]?$")


def _period(cell) -> str | None:
    m = _DATE.match(str(cell).strip()) if isinstance(cell, str) else None
    if not m or m.group(1).lower() not in _MON:
        return None
    yy = int(m.group(2))
    return f"{1900 + yy if yy >= 50 else 2000 + yy}-{_MON[m.group(1).lower()]:02d}"


def parse_c30(path_or_bytes) -> list[tuple[str, float]]:
    """XLSX → [(YYYY-MM, 백만 달러)] 오름차순. 'Data center' 머리말이 없으면 오류"""
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    ws = openpyxl.load_workbook(src, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    hdr_i = next((i for i, r in enumerate(rows[:15]) if r and str(r[0]).strip() == "Date"), None)
    if hdr_i is None:
        raise ValueError("'Date' 머리행을 찾지 못함 — 레이아웃 변경 확인 필요")
    hdr = [str(c).strip() if c is not None else "" for c in rows[hdr_i]]
    if hdr.count("Data center") != 1:
        raise ValueError(f"'Data center' 열이 정확히 하나가 아님: {hdr.count('Data center')}개")
    col = hdr.index("Data center")
    out = []
    for r in rows[hdr_i + 1:]:
        p = _period(r[0]) if r else None
        if p and col < len(r) and isinstance(r[col], (int, float)):
            out.append((p, float(r[col])))
    return sorted(out)


def collect() -> dict:
    from database import get_connection
    stored, series, latest, errors = 0, [], {}, {}
    conn = get_connection()
    try:
        for fname, key, unit in FILES:
            try:
                res = requests.get(BASE + fname, headers=UA, timeout=60, allow_redirects=True)
                res.raise_for_status()
                rows = parse_c30(res.content)
                if not rows:
                    raise ValueError("Data center 값 0건")
            except Exception as e:  # noqa: BLE001 — 파일별 실패는 status/errors로 드러낸다
                errors[key] = str(e)
                continue
            stored += upsert(conn, key, rows, unit, f"{SOURCE} ({fname})")
            series.append(key)
            latest[key] = rows[-1][0]
        conn.commit()
    finally:
        conn.close()
    status = "error" if not series else ("partial" if errors else "ok")
    return {"stored": stored, "series": series, "latest": latest, "status": status,
            **({"errors": errors} if errors else {})}
