"""중국 해관총서(GACC) 영문 월보 — 반도체 수입 월간 수집 (docs/specs/value-chain.md §7, LLM 0).

출처: english.customs.gov.cn Monthly Bulletin 표 (14) "Major Import Commodities in Quantity and Value" (키 없는 정적 HTML).
  연도 목차  statics/report/monthly.html(올해), monthly2018.html … (지난해들) → 표마다 월별 GUID 페이지 링크
  표 페이지  열: 품목, 수량단위, [당월 수량·금액], [1~당월 누계 수량·금액], 증감률 2열. 금액 단위 US$1,000(머리말 확인)
시리즈(당월 값, 누계 아님):
  gacc:ic_import_usd / gacc:ic_import_qty      "Electronic integrated circuits" 금액(천 달러)·수량(1억 개)
  gacc:semi_equip_import_usd                    "Semiconductor Manufacturing Equipments" 총계(천 달러) — 2020년부터만 있다
  gacc:ic_equip_import_usd                      그 하위 "Machinery for manufacturing SC devices or IC"(천 달러)
주의(2026-10 전수 확인):
  - 2018~2019 표에는 장비 총계 행이 없고 하위 행 라벨이 "Machines&apparatus for making SC devices and IC"다.
    IC 수량 단위도 MN(백만 개)이라 1억 개로 환산한다(÷100). 모르는 단위는 오류.
  - 당월 열이 없고 누계만 있는 달은 당월 = 누계 − 전월 누계로 도출하고 notes에 남긴다.
    2020-02는 1~2월 합산 누계만 공시(1월 페이지 없음) → 2020-01·02는 도출 불가 공백. 2024-09·10은 목차에 링크가 없다.
  - 2026-01처럼 당월 열만 있는 1월 페이지도 있다. 일부 페이지는 행 앞에 빈 칸이 끼어 있다(2022-02).
  - 필요한 행을 못 찾으면 조용히 건너뛰지 않고 errors에 달·행 이름을 남긴다(status partial).
"""
from __future__ import annotations

import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

from pipeline.ext_series import upsert

INDEX_URL = "http://english.customs.gov.cn/statics/report/monthly.html"
YEAR_INDEX_URL = "http://english.customs.gov.cn/statics/report/monthly{year}.html"
FIRST_YEAR = 2018
RECENT = 3  # 일일 실행이 다시 받는 최근 달 수(수정치 반영)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
UNIT_USD = "USD thousand"
UNIT_QTY = "100 million pieces"
SOURCE = "GACC Monthly Bulletin (14) Major Import Commodities"
TABLE_TITLE = "Major Import Commodities in Quantity and Value"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# 행 키 → 라벨 별칭(정규화 후 완전 일치). 첫 항목이 오류 메시지에 쓰인다
ROWS = {
    "ic": ("Electronic integrated circuits",),
    "semi_equip": ("Semiconductor Manufacturing Equipments", "Semiconductor Manufacturing Equipment"),
    "ic_equip": ("Machinery for manufacturing SC devices or IC", "Machines&apparatus for making SC devices and IC"),
}
ROW_SINCE = {"semi_equip": 2020}  # 이 해 전 표에는 행 자체가 없다(누락 아님)
QTY_FACTOR = {"100MN": 1.0, "MN": 0.01}  # IC 수량 → 1억 개
SERIES = {  # 시리즈 → (행 키, 0=수량/1=금액, 단위)
    "gacc:ic_import_usd": ("ic", 1, UNIT_USD),
    "gacc:ic_import_qty": ("ic", 0, UNIT_QTY),
    "gacc:semi_equip_import_usd": ("semi_equip", 1, UNIT_USD),
    "gacc:ic_equip_import_usd": ("ic_equip", 1, UNIT_USD),
}


def _norm(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


_ALIAS = {_norm(a): key for key, aliases in ROWS.items() for a in aliases}


def _num(cell: str) -> float | None:
    s = cell.replace(",", "").strip()
    return None if s in ("", "-", "--") else float(s)


def parse_index(html: str) -> dict[int, str]:
    """연도 목차 → {월: 표(14) 페이지 URL}. 링크 없는 달(<span>)은 미공시"""
    soup = BeautifulSoup(html, "lxml")
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) >= 2 and TABLE_TITLE.lower() in tds[0].get_text(" ", strip=True).lower():
            out = {}
            for a in tds[1].find_all("a", href=True):
                name = a.get_text(strip=True).rstrip(".")[:3]
                if name not in MONTHS:
                    raise ValueError(f"목차 월 이름 이상: {a.get_text(strip=True)!r}")
                out[MONTHS.index(name) + 1] = a["href"].strip()
            return out
    raise ValueError(f"목차에서 표(14) '{TABLE_TITLE}' 행을 찾지 못함 — 목차 레이아웃 확인 필요")


def parse_table(html: str) -> dict:
    """표(14) 페이지 → {"year", "month", "rows": {키: {"unit", "month": (수량, 금액)|None, "ytd": ...}}}.
    IC 수량은 1억 개로 환산. 구조(제목·단위·머리행)가 낯설면 ValueError"""
    soup = BeautifulSoup(html, "lxml")
    text = re.sub(r"\s+", " ", soup.get_text(" ").replace("\xa0", " "))
    m = re.search(r"Quantity and Value\s*,\s*(?:(\d{1,2})\s*-\s*)?(\d{1,2})\s*\.\s*(\d{4})", text)
    if not m:
        raise ValueError("제목에서 'Quantity and Value,월.연도'를 찾지 못함 — 페이지 확인 필요")
    year, month = int(m.group(3)), int(m.group(2))
    if not re.search(r"Unit\s*:\s*US\$\s*1,000(?![,\d])", text):
        raise ValueError(f"{year}-{month:02d} 금액 단위 머리말('Unit:US$1,000')을 찾지 못함")

    rows = []
    for tr in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True).replace("\xa0", " ")).strip()
                 for td in tr.find_all("td")]
        while cells and not cells[0]:
            cells.pop(0)  # 일부 페이지는 행 앞에 빈 칸이 있다
        if cells:
            rows.append(cells)
    header = next((r for r in rows if r[0] == "Commodity"), None)
    if header is None:
        raise ValueError(f"{year}-{month:02d} 머리행('Commodity')을 찾지 못함")
    kinds = []  # 기간 열 순서: "month" | "ytd"
    for h in header[2:]:
        if h.lower().startswith("percentage"):
            break
        h2 = h.replace(" ", "")
        if re.fullmatch(r"\d{1,2}", h2) and int(h2) == month:
            kinds.append("month")
        elif re.fullmatch(rf"1(?:to|-){month}", h2):
            kinds.append("ytd")
        else:
            raise ValueError(f"{year}-{month:02d} 기간 머리 {h!r} 해석 불가")
    if not kinds:
        raise ValueError(f"{year}-{month:02d} 기간 열이 없음")

    found: dict[str, dict] = {}
    for r in rows:
        key = _ALIAS.get(_norm(r[0]))
        if key is None:
            continue
        if key in found:
            raise ValueError(f"{year}-{month:02d} '{ROWS[key][0]}' 행이 두 번 나옴")
        if len(r) < 2 + 2 * len(kinds):
            raise ValueError(f"{year}-{month:02d} '{r[0]}' 행 칸 수 부족: {r}")
        unit, factor = r[1], 1.0
        if key == "ic":
            if unit not in QTY_FACTOR:
                raise ValueError(f"{year}-{month:02d} IC 수량 단위 {unit!r} 모름 (100MN/MN만 앎)")
            factor = QTY_FACTOR[unit]
        rec = {"unit": unit, "month": None, "ytd": None}
        for i, kind in enumerate(kinds):
            qty, val = _num(r[2 + 2 * i]), _num(r[3 + 2 * i])
            rec[kind] = (qty * factor if qty is not None else None, val)
        found[key] = rec
    return {"year": year, "month": month, "rows": found}


def required_rows(year: int) -> list[str]:
    return [k for k in ROWS if year >= ROW_SINCE.get(k, 0)]


def derive(pages: dict[tuple[int, int], dict]) -> tuple[dict[str, list[tuple[str, float]]], list[str], list[str]]:
    """페이지들 → ({시리즈: [(YYYY-MM, 당월 값)]}, notes, gaps). 당월 열 우선, 없으면 누계 − 전월 누계(같은 해)"""
    out: dict[str, list[tuple[str, float]]] = {s: [] for s in SERIES}
    notes, gaps = [], []

    def ytd(y, m, key, idx):
        p = pages.get((y, m))
        rec = p and p["rows"].get(key)
        if not rec:
            return None
        if rec["ytd"]:
            return rec["ytd"][idx]
        return rec["month"][idx] if m == 1 and rec["month"] else None

    for (y, m), page in sorted(pages.items()):
        period = f"{y}-{m:02d}"
        for series, (key, idx, _) in SERIES.items():
            rec = page["rows"].get(key)
            if rec is None:
                continue  # 행 누락은 collect가 errors로 보고
            if rec["month"] and rec["month"][idx] is not None:
                out[series].append((period, rec["month"][idx]))
                continue
            cur = ytd(y, m, key, idx)
            prev = 0.0 if m == 1 else ytd(y, m - 1, key, idx)
            if cur is not None and prev is not None:
                out[series].append((period, cur - prev))
                notes.append(f"{period} {series}: 당월 열 없음 → 누계−전월누계로 도출")
            else:
                gaps.append(f"{period} {series}: 당월 값 없음, 전월 누계도 없어 도출 불가")
    return out, notes, gaps


def _get(url: str) -> str:
    res = requests.get(url, headers=UA, timeout=30)
    time.sleep(1)  # 예의상 요청 간 1초
    res.raise_for_status()
    return res.content.decode("utf-8", "replace")


def collect(backfill: bool = False) -> dict:
    """backfill=True면 2018년부터 모든 연도, 아니면 올해 목차 + 최근 RECENT개월만 다시 받는다"""
    from database import get_connection
    errors: list[str] = []
    indexes: list[tuple[str, dict[int, str], bool]] = []  # (목차 URL, {월: URL}, 지난해 목차 여부)
    this_year = date.today().year
    idx_urls = [(YEAR_INDEX_URL.format(year=y), True) for y in range(FIRST_YEAR, this_year)] if backfill else []
    idx_urls.append((INDEX_URL, False))
    for url, past in idx_urls:
        try:
            indexes.append((url, parse_index(_get(url)), past))
        except Exception as e:  # noqa: BLE001 — 수집 실패는 status로 드러낸다
            errors.append(f"목차 {url} 실패: {e}")
    if not backfill and indexes and len(indexes[0][1]) < RECENT:  # 연초: 지난해 목차에서 모자란 달을 채운다
        url = YEAR_INDEX_URL.format(year=this_year - 1)
        try:
            indexes.insert(0, (url, parse_index(_get(url)), True))
        except Exception as e:  # noqa: BLE001
            errors.append(f"목차 {url} 실패: {e}")

    targets = [(url, m, link, past) for url, links, past in indexes for m, link in sorted(links.items())]
    if not backfill:
        targets = targets[-RECENT:]
    pages: dict[tuple[int, int], dict] = {}
    index_year: dict[str, int] = {}  # 목차 URL → 페이지 제목에서 읽은 연도
    seen: set[str] = set()
    for idx_url, m, link, _ in targets:
        if link in seen:
            continue
        seen.add(link)
        try:
            page = parse_table(_get(link))
            if page["month"] != m:
                raise ValueError(f"목차는 {m}월인데 페이지 제목은 {page['month']}월")
            pages[(page["year"], m)] = page
            index_year[idx_url] = page["year"]
        except Exception as e:  # noqa: BLE001
            errors.append(f"{idx_url} {m}월 표(14) {link} 실패: {e}")

    for (y, m), page in sorted(pages.items()):
        for key in required_rows(y):
            if key not in page["rows"]:
                errors.append(f"{y}-{m:02d} 표(14)에서 '{ROWS[key][0]}' 행을 찾지 못함 — 라벨 변경 확인 필요")

    data, notes, gaps = derive(pages)
    if backfill:  # 목차에 링크가 없는 달(지난해는 1~12월, 올해는 마지막 공시월까지)
        for url, links, past in indexes:
            if url in index_year and links:
                last = 12 if past else max(links)
                gaps += [f"{index_year[url]}-{mm:02d}: 목차에 표(14) 링크 없음" for mm in range(1, last + 1) if mm not in links]

    stored, series = 0, []
    conn = get_connection()
    try:
        for key, rows in data.items():
            if rows:
                stored += upsert(conn, key, rows, SERIES[key][2], SOURCE)
                series.append(key)
        conn.commit()
    finally:
        conn.close()
    latest = max((p for rows in data.values() for p, _ in rows), default=None)
    if not stored and not errors:
        errors.append("저장할 행 0개 — 목차에 링크가 없거나 모든 달이 도출 불가")
    status = "error" if not stored else ("partial" if errors else "ok")
    return {"stored": stored, "series": series, "latest": latest, "status": status, "pages": len(pages),
            **({"error": "; ".join(errors), "errors": errors} if errors else {}),
            **({"gaps": gaps} if gaps else {}), **({"notes": notes} if notes else {})}
