"""UN Comtrade 미러 데이터 — 중국의 반도체 장비 수입을 공급국별로 (docs/specs/value-chain.md §7, LLM 0).

출처: UN Comtrade 키 없는 공개 미리보기 API (API 키 미사용 — 사용자 결정).
  자료     /public/v1/preview/C/M/HS?reporterCode=..&period=YYYYMM&partnerCode=156&cmdCode=8486&flowCode=X
  가용 월  /public/v1/getDA/C/M/HS?reporterCode=N   (보고국별 발표된 월 목록)
중국 통계 대신 수출국(일본 392·네덜란드 528·미국 842)이 신고한 대중국 수출(flow X)을 쓴다 = 미러 데이터.
품목 HS 8486(반도체·디스플레이 제조장비 합계). 상대국은 중국 156만 — 홍콩 경유분은 HS 8486에서 비중이 작아 제외(사용자 결정).
값은 fobvalue(USD, 수출 FOB)를 쓰고, 없을 때만 primaryValue로 대신한다(2026-10 응답 확인: 수출은 둘이 같고 cifvalue는 null).
제약: 호출당 1개월·500건, 호출 간격이 2~3초보다 짧으면 HTTP 429 → 3초 이상 간격 + 429 시 지수 백오프, 실행당 호출 상한.
  키 없는 호출은 할당량도 있다(2026-10 백필에서 약 200회째 HTTP 403 'Out of call volume quota', 약 1시간 뒤 회복) → 즉시 멈추고, 못 받은 월은 다음 일일 실행이 이어받는다.
월 자료가 비어 있으면 저장하지 않는다(0으로 채우지 않음) — missing으로 센다.
갱신: 보고국은 과거 월을 수정 발표하므로 일일 실행은 보고국별 최근 가용 4개월 + 아직 없는 월을 다시 받는다.
"""
from __future__ import annotations

import re
import time
from datetime import date

import requests

from pipeline.ext_series import read, upsert

BASE = "https://comtradeapi.un.org/public/v1"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
UNIT = "USD"
SOURCE = "UN Comtrade public preview (mirror, HS 8486, flow X)"
REPORTERS = {392: "comtrade:JP:8486:CN", 528: "comtrade:NL:8486:CN", 842: "comtrade:US:8486:CN"}
PARTNER, CMD, FLOW = 156, "8486", "X"
START = "2019-01"
RECENT = 4            # 일일 재수집 월 수(수정 반영)
STALE_MONTHS = 6      # 최신 가용 월이 이보다 오래되면 실패로 드러낸다
MAX_CALLS = 320       # 실행당 호출 상한(가용 월 조회 포함). 백필 ≈ 3 + 92개월×3 + 재시도 여유
SPACING = 3.2         # 호출 간 최소 간격(초)
RETRIES = 4


def _ym(period) -> str:
    """202406 / '202406' → '2024-06'"""
    s = str(period)
    return f"{s[:4]}-{s[4:6]}"


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) * 12 + int(b[5:])) - (int(a[:4]) * 12 + int(a[5:]))


def parse_preview(payload: dict) -> float | None:
    """preview 응답 → 합계 값(USD). 해당 월 자료가 없으면 None. 합계 행이 여러 개면 오류(조용히 더하지 않음)"""
    if payload.get("error"):
        raise ValueError(f"API 오류: {payload['error']}")
    rows = [r for r in payload.get("data") or []
            if r.get("flowCode") == FLOW and str(r.get("cmdCode")) == CMD and r.get("partnerCode") == PARTNER
            and r.get("partner2Code") in (0, None) and r.get("customsCode") in ("C00", None)
            and r.get("motCode") in (0, None)]
    if not rows:
        return None
    if len(rows) > 1:
        raise ValueError(f"합계 행이 {len(rows)}개 — 응답 구조 변경 확인 필요")
    r = rows[0]
    value = r.get("fobvalue") if r.get("fobvalue") is not None else r.get("primaryValue")
    return float(value) if value is not None else None


def parse_availability(payload: dict) -> list[str]:
    """getDA 응답 → 가용 월 목록 ['YYYY-MM', ...] (정렬)"""
    if payload.get("error"):
        raise ValueError(f"API 오류: {payload['error']}")
    return sorted({_ym(r["period"]) for r in payload.get("data") or [] if r.get("period")})


def months_to_fetch(available: list[str], stored: set[str], backfill: bool) -> list[str]:
    """가용 월 중 받을 월. backfill = START 이후 전부, 일일 = 최근 RECENT개 + 아직 없는 월(중단된 백필 이어받기)"""
    avail = [p for p in available if p >= START]
    if backfill:
        return avail
    recent = set(avail[-RECENT:])
    return [p for p in avail if p in recent or p not in stored]


class _Client:
    """간격 유지 + 429 지수 백오프 + 호출 상한"""

    def __init__(self, max_calls: int = MAX_CALLS):
        self.calls, self.max_calls, self._last = 0, max_calls, 0.0

    def get(self, path: str, params: dict) -> dict:
        for attempt in range(RETRIES + 1):
            if self.calls >= self.max_calls:
                raise _CapReached(f"호출 상한 {MAX_CALLS}회 도달 — 다음 실행에서 이어받음")
            wait = SPACING - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self.calls += 1
            res = requests.get(f"{BASE}/{path}", params=params, headers=UA, timeout=60)
            self._last = time.monotonic()
            if res.status_code == 403 and "quota" in res.text.lower():
                raise _CapReached(f"Comtrade 키 없는 호출 할당량 소진(HTTP 403, 이번 실행 {self.calls}회째: "
                                  f"{res.text[:120].strip()}) — 다음 실행에서 이어받음")
            if res.status_code == 429 and attempt < RETRIES:
                hint = re.search(r"in (\d+) seconds", res.text)
                time.sleep(max(SPACING * 2 ** attempt, int(hint.group(1)) if hint else 0))
                continue
            res.raise_for_status()
            return res.json()


class _CapReached(Exception):
    pass


def collect(backfill: bool = False) -> dict:
    from database import get_connection

    client = _Client()
    today = date.today().strftime("%Y-%m")
    stored_n, series, latest, missing, errors, problems = 0, [], {}, {}, {}, []
    capped = False
    conn = get_connection()
    try:
        for code, key in REPORTERS.items():
            if capped:
                errors[key] = "호출 상한·할당량 소진으로 건너뜀"
                continue
            rows, gaps = [], []
            try:
                available = parse_availability(client.get("getDA/C/M/HS", {"reporterCode": code}))
                if not available:
                    raise ValueError("가용 월 0개")
                if _months_between(available[-1], today) > STALE_MONTHS:
                    problems.append(f"{key}: 최신 가용 월 {available[-1]} — {STALE_MONTHS}개월 넘게 갱신 없음")
                for p in months_to_fetch(available, set(read(conn, key)), backfill):
                    value = parse_preview(client.get("preview/C/M/HS", {
                        "reporterCode": code, "period": p.replace("-", ""), "partnerCode": PARTNER,
                        "cmdCode": CMD, "flowCode": FLOW}))
                    if value is None:
                        gaps.append(p)
                    else:
                        rows.append((p, value))
            except _CapReached as e:  # 상한·할당량 소진은 남은 보고국도 멈춘다
                capped = True
                errors[key] = str(e)
            except Exception as e:  # noqa: BLE001 — 수집 실패는 status로 드러낸다
                errors[key] = str(e)
            if rows:  # 상한·오류로 중간에 끊겨도 받은 월까지는 저장한다
                stored_n += upsert(conn, key, rows, UNIT, SOURCE)
                series.append(key)
                latest[key] = max(rows)[0]
                conn.commit()
            if gaps:
                missing[key] = gaps
    finally:
        conn.close()

    if problems:
        errors["stale"] = "; ".join(problems)
    status = "error" if not series else ("partial" if errors else "ok")
    out = {"stored": stored_n, "series": series, "latest": max(latest.values()) if latest else None,
           "latest_by_series": latest, "status": status, "unit": UNIT, "calls": client.calls}
    if missing:
        out["missing"] = missing
    if errors:
        out["errors"] = errors
        out["error"] = " / ".join(f"{k}: {v}" for k, v in errors.items())
    return out
