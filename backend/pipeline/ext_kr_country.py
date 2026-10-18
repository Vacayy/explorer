"""한국 수출 국가별 — 관세청 품목별 국가별 수출입실적 (docs/specs/value-chain.md §13, LLM 0).

공공데이터포털 data.go.kr 관세청_품목별 국가별 수출입실적(GW):
  GET https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList
  params: serviceKey · strtYymm · endYymm(1년 이내) · hsSgn · cntyCd(필수, 2자리)
  응답: 하위 HS 행(hsCd·year 'YYYY.MM'·expDlr…) + '총계' 행 — 월 행만 합산하고 총계 행은 버린다(pipeline/trade와 같은 규율).
키는 품목별 수출입실적과 같은 DATA_GO_KR_KEY(서비스별 활용 신청 필요).

시리즈:
- kr_exp:8486x:CN — 반도체 장비(평판디스플레이 장비 848630 제외) 중국향. **중국 반도체 회사의 장비 구매와, 삼성전자·SK하이닉스가
  자기 중국 공장(시안·우시·다롄)으로 보내는 설비가 함께 담기고 둘을 나눌 수 없다** — 그래서 중국 수요 칸의 주 관측으로 쓰지 않고
  교차 확인으로만 둔다(D-259).
- kr_exp:8542:CN·HK, kr_exp:854232:CN·HK — 집적회로·메모리 중국·홍콩향. IC는 홍콩을 거쳐 중국 본토로 들어가는 물량이 커서 홍콩을 함께 본다.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import date

import requests

from config import DATA_GO_KR_KEY
from pipeline.ext_series import upsert
from pipeline.trade import _norm_period, _num, _throttle

BASE = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"
UNIT, SOURCE = "USD", "관세청 품목별 국가별 수출입실적"
START = "201901"
# 시리즈 → (HS 조회 부호, 국가, 제외할 하위 HS)
SERIES = {"kr_exp:8486x:CN": ("8486", "CN", {"848630"}),
          "kr_exp:8542:CN": ("8542", "CN", set()), "kr_exp:8542:HK": ("8542", "HK", set()),
          "kr_exp:854232:CN": ("854232", "CN", set()), "kr_exp:854232:HK": ("854232", "HK", set())}


def parse(xml_text: str, exclude: set[str]) -> dict[str, float]:
    """응답 XML → {YYYY-MM: 수출 USD 합}. 총계 행(월 없음)과 제외 HS는 버린다. 오류 응답은 예외 — 조용한 빈 결과 금지"""
    root = ET.fromstring(xml_text)
    err = root.findtext(".//errMsg")
    if err:
        raise RuntimeError(f"관세청 국가별 API: {err} / {root.findtext('.//returnAuthMsg')}")
    code = (root.findtext(".//resultCode") or "").strip()
    if code not in ("00", "0"):
        raise RuntimeError(f"관세청 국가별 API 오류 code={code} msg={root.findtext('.//resultMsg')}")
    out: dict[str, float] = {}
    for it in root.iter("item"):
        p = _norm_period(it.findtext("year"))
        hs = (it.findtext("hsCd") or "").strip()
        if not p or any(hs.startswith(x) for x in exclude):
            continue
        out[p] = out.get(p, 0.0) + _num(it.findtext("expDlr"))
    return out


def _fetch(hs: str, cnty: str, strt: str, end: str, exclude: set[str]) -> dict[str, float]:
    for attempt in range(4):
        _throttle()
        r = requests.get(BASE, params={"serviceKey": DATA_GO_KR_KEY, "strtYymm": strt, "endYymm": end, "hsSgn": hs,
                                       "cntyCd": cnty, "numOfRows": 1000, "pageNo": 1}, timeout=30)
        if r.status_code == 200:
            return parse(r.text, exclude)
        if r.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep(2 ** attempt)
    raise RuntimeError(f"관세청 국가별 API HTTP {r.status_code}")


def _windows(strt: str, end: str) -> list[tuple[str, str]]:
    sy, ey = int(strt[:4]), int(end[:4])
    return [(f"{y}{(strt[4:] if y == sy else '01')}", f"{y}{(end[4:] if y == ey else '12')}") for y in range(sy, ey + 1)]


def collect(backfill: bool = False) -> dict:
    """backfill=True면 2019-01부터, 아니면 올해(1~3월엔 작년 포함 — 관세청이 매월 전월까지 정정)"""
    from database import get_connection
    if not DATA_GO_KR_KEY:
        return {"status": "error", "stored": 0, "error": "DATA_GO_KR_KEY 미설정"}
    t = date.today()
    end = f"{t.year}{t.month:02d}"
    strt = START if backfill else (f"{t.year - 1}01" if t.month <= 3 else f"{t.year}01")
    stored, failed, latest = 0, [], None
    conn = get_connection()
    try:
        for series, (hs, cnty, excl) in SERIES.items():
            rows: dict[str, float] = {}
            try:
                for ws, we in _windows(strt, end):
                    rows.update(_fetch(hs, cnty, ws, we, excl))
            except Exception as e:  # noqa: BLE001 — 한 시리즈 실패는 남기고 다음으로
                failed.append(f"{series}: {e}"[:160])
                continue
            stored += upsert(conn, series, sorted(rows.items()), UNIT, SOURCE)
            conn.commit()
            if rows:
                latest = max(latest or "", max(rows))
    finally:
        conn.close()
    status = "error" if not stored else "partial" if failed else "ok"
    return {"status": status, "stored": stored, "series": list(SERIES), "latest": latest, **({"error": "; ".join(failed)} if failed else {})}
