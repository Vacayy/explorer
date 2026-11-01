"""일본 재무성 무역통계 품별국별표(수출) 월간 수집 (docs/specs/value-chain.md §7, LLM 0, 키 없음).

출처: 세관 統計表一覧(customs.go.jp/toukei/info/tsdl.htm) → e-Stat 파일 목록 '品別国別表 輸出'(INDEX_URL).
  목록 첫 화면에 연도별 링크가 한 개씩(그 해의 최신 월) 있고, 연도 화면에 HS 부(部)별 CSV 22개가 있다.
  statInfId는 공표마다 바뀌므로 매번 목록을 긁어 '６部 28-38類'·'１６部 84-85類'·'１８部 90-92類' 파일을 찾는다.
CSV(UTF-8) 열: Exp or Imp,Year,HS('9자리'),Country,Unit1,Unit2,...,Value-Year,...,Value-Jan..Value-Dec.
  한 파일 = 그 해 1월~공표월 누계라 월별 열이 따로 있다 → 연도별 최신 파일 하나로 그 해 전체를 덮는다.
  공표월 이후 열은 0으로 채워져 있으므로 목록 제목의 '(輸出 1-M月'까지만 읽는다. 금액 단위 千円.
  세계 합계 행·지역 소계 행은 없다(국가 코드 3자리만) → ALL = 모든 국가 행의 합.
  '38XXXXXXA'처럼 류 단위로 묶인 비밀(秘匿) 행은 어느 9자리에 속하는지 알 수 없어 합산에서 빠진다(과소 가능).
국가 코드(세관 country_e.htm로 확인): 103 한국, 105 중국, 106 대만, 304 미국.
HS는 6자리 접두로 합산한다 — 2026년 확인 9자리 코드:
  8486 = 848610000·848620000·848630000·848640000·848690000, 3707.90 = 370790000,
  3818.00 = 381800100·381800900, 9030.82 = 903082100·903082900, 9031.41 = 903141000.
속보·확보로 계속 수정되므로 항상 덮어쓴다.
"""
from __future__ import annotations

import csv
import html
import io
import re
import time
from datetime import date

import requests

from pipeline.ext_series import upsert

ESTAT = "https://www.e-stat.go.jp"
INDEX_URL = (ESTAT + "/stat-search/files?page=1&layout=datalist&toukei=00350300&tstat=000001013141&cycle=1"
             "&tclass1=000001013180&tclass2=000001013181&cycle_facet=cycle&tclass3val=0&metadata=1&data=1")
DOWNLOAD_URL = ESTAT + "/stat-search/file-download?statInfId={}&fileKind=1"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
UNIT = "JPY thousand"
SOURCE = "財務省貿易統計 品別国別表(輸出) e-Stat"
START_YEAR = 2019
COUNTRIES = {"CN": "105", "TW": "106", "KR": "103", "US": "304"}
# 시리즈 → (HS 접두, 국가 코드 또는 None=전체)
SERIES = {
    **{f"jp_exp:8486:{k}": ("8486", c) for k, c in {"ALL": None, **COUNTRIES}.items()},
    "jp_exp:3707:ALL": ("370790", None),
    "jp_exp:3818:ALL": ("381800", None),
    "jp_exp:903082:ALL": ("903082", None),
    "jp_exp:903141:ALL": ("903141", None),
}
CHAPTERS = sorted({int(p[:2]) for p, _ in SERIES.values()})  # [37, 38, 84, 90]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def parse_index(page: str) -> dict[int, str]:
    """목록 첫 화면 → {연도: 연도 화면 URL}. 연도마다 최신 월 링크 하나"""
    out: dict[int, tuple[int, str]] = {}
    for href, year, month in re.findall(
            r'href="(/stat-search/files\?[^"]*?year=(\d{4})0&amp;[^"]*)" class="stat-item_child">(\d{1,2})月', page):
        y, m = int(year), int(month)
        if y not in out or m > out[y][0]:
            out[y] = (m, ESTAT + html.unescape(href))
    return {y: url for y, (_, url) in out.items()}


def parse_listing(page: str) -> dict[int, tuple[str, int, int]]:
    """연도 화면 → {HS 류(章): (statInfId, 연도, 마지막 월)}. 마지막 월은 '(輸出 1-M月' 범위에서 읽는다.
    제목 예 '2026年8月分 品別国別表 (輸出 1-8月：確報) １６部 84-85類', 연간분 '2024年分 ... (輸出 1-12月：確定)'·'2025年 ... 確々報'"""
    out: dict[int, tuple[str, int, int]] = {}
    titles = re.findall(r'data-value="(\d+)"[^>]*>\s*([^<]*品別国別表[^<]*?)\s*</a>', page)
    for sid, title in titles:
        t = title.translate(_ZEN)
        m = re.match(r"(\d{4})年(?:\d{1,2}月)?分? 品別国別表 \(輸出 (?:1-)?(\d{1,2})月[^)]*\) \d+部 (\d{2})(?:-(\d{2}))?類$", t)
        if not m:
            continue
        if f"statInfId={sid}&fileKind=1" not in page:
            raise ValueError(f"CSV 내려받기 링크 없음: {t}")
        lo, hi = int(m.group(3)), int(m.group(4) or m.group(3))
        for ch in range(lo, hi + 1):
            out[ch] = (sid, int(m.group(1)), int(m.group(2)))
    if titles and not out:
        raise ValueError(f"제목 형식을 하나도 해석 못 함 — 예: {titles[0][1]!r}")
    return out


def aggregate(text: str, year: int, last_month: int, specs: dict) -> tuple[dict[str, list[tuple[str, float]]], set[str]]:
    """CSV 본문 → ({series: [(YYYY-MM, 千円)]}, 합산된 9자리 HS 코드). specs = {series: (HS 접두, 국가 또는 None)}"""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    need = ["Exp or Imp", "Year", "HS", "Country"] + [f"Value-{m}" for m in MONTHS]
    missing = [c for c in need if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"열 {missing} 없음: {reader.fieldnames} — 레이아웃 변경 확인 필요")
    cols = [f"Value-{m}" for m in MONTHS[:last_month]]
    sums = {s: [0.0] * last_month for s in specs}
    hit: set[str] = set()
    codes: set[str] = set()
    for row in reader:
        if row["Exp or Imp"].strip() != "1" or row["Year"].strip() != str(year):
            raise ValueError(f"수출/연도 불일치 행: {row['Exp or Imp']!r}, {row['Year']!r} (기대 1, {year})")
        hs = row["HS"].strip().strip("'")
        if not re.fullmatch(r"\d{2}[0-9XA]{7}", hs):  # '38XXXXXXA' = 류 단위 비밀 합산 행
            raise ValueError(f"HS 코드 형식 이상: {row['HS']!r}")
        country = row["Country"].strip()
        for s, (prefix, cc) in specs.items():
            if hs.startswith(prefix) and (cc is None or cc == country):
                hit.add(s)
                codes.add(hs)
                for i, c in enumerate(cols):
                    sums[s][i] += float(row[c] or 0)
    return ({s: [(f"{year}-{i + 1:02d}", v) for i, v in enumerate(vals)] for s, vals in sums.items() if s in hit},
            codes)


def _get(url: str) -> requests.Response:
    time.sleep(1)  # e-Stat 예의: 요청 간 1초 이상
    res = requests.get(url, headers=UA, timeout=120)
    res.raise_for_status()
    return res


def collect(backfill: bool = False) -> dict:
    from database import get_connection
    t0 = time.time()
    errors: list[str] = []
    rows: dict[str, list[tuple[str, float]]] = {s: [] for s in SERIES}
    codes: set[str] = set()
    try:
        years = parse_index(_get(INDEX_URL).text)
        if not years:
            raise ValueError("연도 링크 0개 — e-Stat 목록 레이아웃 변경 확인 필요")
    except Exception as e:  # noqa: BLE001 — 수집 실패는 status로 드러낸다
        return {"stored": 0, "series": [], "status": "error", "error": f"品別国別表 목록 조회 실패: {e}"}
    today = date.today()
    newest = max(years)
    if backfill:
        want = [y for y in years if y >= START_YEAR]
    else:  # 올해 최신 + 1~3월이면 전년(12월 확정 수정분)도
        want = sorted({newest} | ({today.year - 1} if today.month <= 3 and today.year - 1 in years else set()))
    for year in sorted(want):
        try:
            files = parse_listing(_get(years[year]).text)
            lacking = [ch for ch in CHAPTERS if ch not in files]
            if lacking:
                raise ValueError(f"{lacking}류 파일을 목록에서 못 찾음(찾은 류 {len(files)}개)")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{year}년 목록: {e}")
            continue
        by_file: dict[str, list[int]] = {}
        for ch in CHAPTERS:
            by_file.setdefault(files[ch][0], []).append(ch)
        for sid, chs in by_file.items():
            _, fy, fm = files[chs[0]]
            specs = {s: v for s, v in SERIES.items() if int(v[0][:2]) in chs}
            try:
                if fy != year:
                    raise ValueError(f"제목 연도 {fy} ≠ {year}")
                got, c = aggregate(_get(DOWNLOAD_URL.format(sid)).content.decode("utf-8-sig"), year, fm, specs)
                for s in specs:
                    if s not in got:
                        raise ValueError(f"{s}: 해당 HS 행 0개")
                    rows[s] += got[s]
                codes |= c
            except Exception as e:  # noqa: BLE001
                errors.append(f"{year}년 statInfId={sid}: {e}")

    stored, series = 0, []
    if any(rows.values()):
        conn = get_connection()
        try:
            for s, r in rows.items():
                if r:
                    stored += upsert(conn, s, r, UNIT, SOURCE)
                    series.append(s)
            conn.commit()
        finally:
            conn.close()
    latest = max((p for r in rows.values() for p, _ in r), default=None)
    missing = [s for s in SERIES if s not in series]
    status = "error" if not series else ("partial" if errors or missing else "ok")
    out = {"stored": stored, "series": series, "latest": latest, "status": status, "unit": UNIT,
           "years": sorted(want), "hs_codes": sorted(codes), "seconds": round(time.time() - t0, 1)}
    if errors or missing:
        out["error"] = "; ".join(errors + ([f"누락 시리즈 {missing}"] if missing else []))
    return out
