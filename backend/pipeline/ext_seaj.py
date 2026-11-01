"""SEAJ 일본제 반도체·FPD 제조장비 월간 판매액 수집 (docs/specs/value-chain.md §7, LLM 0).

출처: 日本半導体製造装置協会(SEAJ) 統計資料 페이지의 'バックナンバー' 표 — 半導体·FPD 각각 BIFF .xls 1개.
파일명이 무작위 숫자로 바뀌므로 페이지(Shift_JIS)에서 링크를 긁는다. xls에는 2005-01부터 최신 확정월까지 들어 있다.
SEAJ가 공개하는 값은 **3개월 이동평균**이다(원 월간값은 회원 전용) — 시리즈 이름에 `_3mma`를 붙여 그대로 저장한다.
열: 年 | 月 | 受注額(百万円) | 前年比 | 販売額(百万円) | 前年比 | BB. 販売額(billings)만 쓴다 —
受注額(bookings)은 2010년대 중반 공개가 끊겨 최근 구간이 비어 있다. 단위는 머리행 '販売額(百万円）'에서 확인한다.
월 칸에 '8R'·'7(R)'·'10（R）'처럼 수정 표시가 붙기도 한다. 연도는 1월 행에만 적혀 있어 아래로 이어받는다.
의존: BIFF .xls는 openpyxl로 못 읽고 xlrd가 필요하다. 없으면 조용히 넘기지 않고 status=error로 드러낸다.
"""
from __future__ import annotations

import io
import re
import unicodedata

import requests
from bs4 import BeautifulSoup

from pipeline.ext_series import upsert

PAGE_URL = "https://www.seaj.or.jp/statistics/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
UNIT = "JPY million (3MMA)"
SOURCE = "SEAJ 販売高速報値(3ヶ月平均) バックナンバー"
SERIES = {"semi": "seaj:semi_3mma", "fpd": "seaj:fpd_3mma"}


def parse_backnumber(grid: list[list]) -> list[tuple[str, float]]:
    """시트 격자(행 리스트) → [(YYYY-MM, 백만 엔 3MMA)]. 값이 빈 미래 월 행은 건너뛴다"""
    header_at, col = None, None
    for i, row in enumerate(grid[:20]):
        for j, cell in enumerate(row):
            if isinstance(cell, str) and "販売額" in cell:
                if "百万円" not in cell:
                    raise ValueError(f"販売額 열 단위가 百万円이 아님: {cell!r} — 레이아웃 변경 확인 필요")
                header_at, col = i, j
                break
        if col is not None:
            break
    if col is None:
        raise ValueError("'販売額(百万円)' 머리행을 찾지 못함 — 레이아웃 변경 확인 필요")

    out: list[tuple[str, float]] = []
    year = None
    for row in grid[header_at + 1:]:
        if len(row) <= col:
            continue
        y, m, v = row[0], row[1], row[col]
        if isinstance(y, (int, float)) and 1990 <= int(y) <= 2100:
            year = int(y)
        month = _month(m)
        if year is None or month is None or not isinstance(v, (int, float)):
            continue
        out.append((f"{year}-{month:02d}", float(v)))
    return out


def _month(cell) -> int | None:
    """월 칸: 8.0 / 8 / '8R'·'8(R)'·'10（R）'(수정치 표시, 전각 괄호 포함) → 8"""
    if isinstance(cell, (int, float)):
        m = int(cell)
    elif isinstance(cell, str) and (hit := re.fullmatch(r"\s*(\d{1,2})\s*(?:\(\s*R\s*\)|R)?\s*", unicodedata.normalize("NFKC", cell))):
        m = int(hit.group(1))
    else:
        return None
    return m if 1 <= m <= 12 else None


def _read_grids(content: bytes) -> list[list[list]]:
    """BIFF .xls → 시트별 격자. xlrd 미설치면 명시적으로 실패"""
    try:
        import xlrd  # noqa: F401
    except ImportError as e:
        raise RuntimeError("xlrd 미설치 — SEAJ 백넘버는 BIFF .xls라 openpyxl로 못 읽는다 (venv에 xlrd 필요)") from e
    import pandas as pd
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, engine="xlrd")
    return [df.astype(object).where(df.notna(), None).values.tolist() for df in sheets.values()]


def _backnumber_links() -> dict[str, str]:
    """統計資料 페이지 → {'semi': url, 'fpd': url}. 'バックナンバー' 표에서 .xls 링크를 행 제목으로 구분한다"""
    res = requests.get(PAGE_URL, headers=UA, timeout=30)
    res.raise_for_status()
    soup = BeautifulSoup(res.content.decode("shift_jis", errors="replace"), "html.parser")
    links: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"\.xls$", re.I))
        if a is None:
            continue
        label = tr.get_text(" ", strip=True)
        if "半導体" in label:
            links.setdefault("semi", requests.compat.urljoin(PAGE_URL, a["href"]))
        elif "FPD" in label:
            links.setdefault("fpd", requests.compat.urljoin(PAGE_URL, a["href"]))
    if not links:
        raise ValueError("統計資料 페이지에서 バックナンバー .xls 링크를 찾지 못함")
    return links


def _parse_file(content: bytes) -> list[tuple[str, float]]:
    for grid in _read_grids(content):
        try:
            rows = parse_backnumber(grid)
        except ValueError:
            continue  # 차트 시트 등 표가 없는 시트
        if rows:
            return rows
    raise ValueError("어느 시트에서도 販売額 시계열을 찾지 못함")


def collect() -> dict:
    import time

    from database import get_connection
    try:
        links = _backnumber_links()
    except Exception as e:  # noqa: BLE001 — 수집 실패는 status로 드러낸다
        return {"stored": 0, "series": [], "latest": {}, "status": "error", "error": str(e)}

    parsed: dict[str, tuple[str, list[tuple[str, float]]]] = {}
    errors: dict[str, str] = {}
    for kind, url in links.items():
        try:
            time.sleep(1)
            res = requests.get(url, headers=UA, timeout=60)
            res.raise_for_status()
            parsed[SERIES[kind]] = (url, _parse_file(res.content))
        except Exception as e:  # noqa: BLE001
            errors[SERIES[kind]] = str(e)

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
    missing = [k for k in SERIES.values() if k not in series]
    status = "error" if not series else ("partial" if missing else "ok")
    return {"stored": stored, "series": series, "latest": latest, "status": status, "unit": UNIT,
            "urls": links, **({"missing": missing} if missing else {}), **({"errors": errors} if errors else {})}
