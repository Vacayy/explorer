"""국내 종목 도시에 원천 수집 — 종목 마스터·DART 공시 목록·분기 재무제표 (launchd krcompany).

배경(2026-10-16 실측): 도시에는 재무를 `stored_only`로 읽기만 하고, 수집은 발견 조사 버튼에서만 일어나 19개사에 머물렀다.
공시는 열 때 수집하던 옛 공시 탭이 내비에서 빠진 뒤 09-16에서 멈췄고, 종목 마스터는 `seed_companies.py` 수동 실행(07-06)뿐이었다.

- 대상 순서 `targets`: 보유(portfolio) → 관심(watch) 묶음 종목 → 최신 시가총액 상위 `TOP_N`.
- 예산: 한 번 실행의 DART 호출을 `DAILY_BUDGET`회로 묶는다. OpenDART 일 한도(약 2만 회)를 기업활동 스캔(30분 체인)·
  포트폴리오 알림·발견 조사와 나눠 쓰므로 여유를 크게 둔다. 예산 소진은 실패가 아니라 남은 양으로 요약에 남는다.
- 멱등: 재무는 이미 저장된 (기업, 연도, 보고서)를 건너뛰고, DART '데이터 없음'(013)은 cache_meta에 음성 캐시한다.
  공시는 rcp_no 기준 INSERT OR IGNORE.
- 상태: 한도 초과(020)·인증 오류·연속 네트워크 실패는 그 단계를 멈추고 status=error, 개별 요청 실패는 partial.
- 저장은 원본 그대로(`_store_financial_df`). 계정명 정규화·CFS 우선 OFS 대체·분기 계산(CF 차감, IS/CIS Q4=연간−(Q1+Q2+Q3), D-183)은
  조회 경로 `_build_financial_response`가 한다. 수집은 기간마다 CFS를 먼저 받고, 없을 때만 OFS를 받는다.
"""
from __future__ import annotations

import io
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta

import requests

DART = "https://opendart.fss.or.kr/api/"
DAILY_BUDGET = 3000        # 실행 1회(=하루 1회 스케줄)의 DART 호출 상한
TOP_N = 300                # 묶음 종목 다음으로 채울 시가총액 상위 기업 수
FIN_YEARS = 4              # 올해 포함 과거 4개 연도까지(도시에 분기표 years=4와 같은 범위)
SWEEP_DAYS = 3             # 전 시장 공시 목록 재확인 창(노트북 수면으로 하루 이틀 밀려도 메운다)
HISTORY_DAYS = 365         # 대상 기업 첫 수집 때 받는 공시 이력
HISTORY_PAGES = 3          # 기업당 이력 최대 300건
MAX_NET_FAILS = 5          # 연속 네트워크 실패가 이만큼이면 망 장애로 보고 단계를 멈춘다
MIN_LISTED = 2000          # 종목 마스터 응답의 상장사 수가 이보다 적으면 깨진 응답으로 보고 쓰지 않는다

# (보고서 코드, 기간 말일 월·일)
REPORTS = (("11013", 3, 31), ("11012", 6, 30), ("11014", 9, 30), ("11011", 12, 31))
FILING_LAG = {"11013": 30, "11012": 30, "11014": 30, "11011": 60}
FATAL = {"010": "등록되지 않은 키", "011": "사용할 수 없는 키", "012": "접근할 수 없는 IP",
         "020": "요청 제한 초과", "901": "키 기간 만료", "800": "시스템 점검"}


class BudgetExhausted(Exception):
    """이번 실행의 DART 호출 예산을 다 썼다 — 실패가 아니라 다음 실행으로 넘긴다."""


class DartFatal(Exception):
    """한도 초과·인증 오류·망 장애 — 같은 실행에서 더 부르면 안 된다."""


class DartRequestError(Exception):
    """요청 하나의 네트워크/HTTP 실패. 메시지에 URL(인증키 포함)을 싣지 않는다."""


class DartClient:
    """호출 수를 세는 얇은 OpenDART 클라이언트. 여러 단계가 같은 인스턴스로 예산을 나눠 쓴다."""

    def __init__(self, key: str, budget: int = DAILY_BUDGET, session=None, pause: float = 0.05):
        self.key, self.budget, self.calls, self.pause = key, budget, 0, pause
        self._session = session or requests
        self._net_fails = 0

    def remaining(self) -> int:
        return self.budget - self.calls

    def _request(self, endpoint: str, params: dict):
        if not self.key:
            raise DartFatal("DART_API_KEY 없음")
        if self.calls >= self.budget:
            raise BudgetExhausted()
        self.calls += 1
        try:
            r = self._session.get(DART + endpoint, params={"crtfc_key": self.key, **params}, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            self._net_fails += 1
            if self._net_fails >= MAX_NET_FAILS:
                raise DartFatal(f"연속 네트워크 실패 {self._net_fails}회 ({type(e).__name__})") from None
            raise DartRequestError(type(e).__name__) from None
        self._net_fails = 0
        if self.pause:
            time.sleep(self.pause)
        return r

    def json(self, endpoint: str, params: dict) -> dict:
        r = self._request(endpoint, params)
        try:
            body = r.json()
        except ValueError:
            raise DartRequestError("JSON 아님") from None
        status = str(body.get("status", ""))
        if status in FATAL:
            raise DartFatal(f"DART {status} {FATAL[status]}")
        return body

    def content(self, endpoint: str, params: dict) -> bytes:
        return self._request(endpoint, params).content


# ── 대상 ──────────────────────────────────────────────────────────────────

def targets(conn, top_n: int = TOP_N) -> list[dict]:
    """수집 순서: 보유 → 관심 묶음 → 최신 시총 상위. corp_code 기준 중복 제거."""
    out, seen = [], set()

    def add(rows, tier):
        for r in rows:
            corp = r[1]
            if corp and corp not in seen:
                seen.add(corp)
                out.append({"stock_code": r[0], "corp_code": corp, "tier": tier})

    add(conn.execute("""
        SELECT m.stock_code, c.corp_code, g.kind FROM stock_group_members m
        JOIN stock_groups g ON g.id = m.group_id JOIN companies c ON c.stock_code = m.stock_code
        WHERE g.kind = 'portfolio' ORDER BY m.id""").fetchall(), "portfolio")
    add(conn.execute("""
        SELECT m.stock_code, c.corp_code, g.kind FROM stock_group_members m
        JOIN stock_groups g ON g.id = m.group_id JOIN companies c ON c.stock_code = m.stock_code
        WHERE g.kind != 'portfolio' ORDER BY m.id""").fetchall(), "watch")
    add(conn.execute("""
        SELECT p.stock_code, c.corp_code FROM stock_prices p JOIN companies c ON c.stock_code = p.stock_code
        WHERE p.trade_date = (SELECT max(trade_date) FROM stock_prices WHERE market_cap IS NOT NULL)
          AND p.market_cap IS NOT NULL
        ORDER BY p.market_cap DESC LIMIT ?""", (top_n,)).fetchall(), "market_cap")
    return out


# ── 종목 마스터 ───────────────────────────────────────────────────────────

def parse_corp_codes(payload: bytes) -> list[tuple[str, str, str]]:
    """corpCode.xml(zip) → 상장사 (corp_code, corp_name, stock_code). zip이 아니면 DART 오류 본문이다."""
    if not payload.startswith(b"PK"):
        try:
            status = ET.fromstring(payload).findtext("status") or "?"
        except ET.ParseError:
            status = "?"
        if status in FATAL:
            raise DartFatal(f"DART {status} {FATAL[status]}")
        raise DartRequestError(f"corpCode 응답이 zip이 아님 (status {status})")
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    rows = []
    for item in root.iter("list"):
        stock = (item.findtext("stock_code") or "").strip()
        if stock:
            rows.append((item.findtext("corp_code").strip(), (item.findtext("corp_name") or "").strip(), stock))
    return rows


def refresh_companies(conn, client: DartClient) -> dict:
    """DART 고유번호 목록으로 신규 상장 추가·이름/코드 변경 반영. market·sector는 건드리지 않는다."""
    try:
        listed = parse_corp_codes(client.content("corpCode.xml", {}))
    except (DartFatal, DartRequestError, BudgetExhausted) as e:
        return {"status": "error", "reason": str(e) or type(e).__name__, "calls": client.calls}
    if len(listed) < MIN_LISTED:
        return {"status": "error", "reason": f"상장사 {len(listed)}건뿐 — 깨진 응답으로 보고 쓰지 않음"}
    have = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT corp_code, corp_name, stock_code FROM companies")}
    inserted = changed = 0
    for corp, name, stock in listed:
        if corp not in have:
            conn.execute("INSERT INTO companies (corp_code, corp_name, stock_code, updated_at) "
                         "VALUES (?, ?, ?, datetime('now'))", (corp, name, stock))
            inserted += 1
        elif have[corp] != (name, stock):
            conn.execute("UPDATE companies SET corp_name=?, stock_code=?, updated_at=datetime('now') WHERE corp_code=?",
                         (name, stock, corp))
            changed += 1
    conn.commit()
    return {"listed": len(listed), "inserted": inserted, "changed": changed}


# ── 공시 목록 ─────────────────────────────────────────────────────────────

def _store_disclosures(conn, items: list[dict], known: set[str] | None = None) -> int:
    before = conn.total_changes
    for it in items:
        rcp, corp = it.get("rcept_no"), it.get("corp_code")
        if not rcp or not corp or (known is not None and corp not in known):
            continue
        conn.execute("""INSERT OR IGNORE INTO disclosures
            (rcp_no, corp_code, corp_name, report_nm, rcept_dt, flr_nm, rm, kind, dart_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)""",
            (rcp, corp, it.get("corp_name", ""), it.get("report_nm", ""), it.get("rcept_dt", ""),
             it.get("flr_nm", ""), it.get("rm", ""), f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}"))
    conn.commit()
    return conn.total_changes - before


def _list_pages(client: DartClient, params: dict, max_pages: int | None = None):
    """list.json 페이지 순회 — (페이지 목록, 마지막까지 받았는지). 013(없음)은 빈 목록."""
    page = 1
    while True:
        body = client.json("list.json", {**params, "page_no": page, "page_count": 100})
        status = str(body.get("status"))
        if status == "013":
            return
        if status != "000":
            raise DartRequestError(f"list status {status}")
        yield body.get("list") or []
        total = int(body.get("total_page") or 1)
        if page >= total or (max_pages and page >= max_pages):
            return
        page += 1


def collect_disclosures(conn, client: DartClient, tgts: list[dict], today: date,
                        sweep_days: int = SWEEP_DAYS) -> dict:
    """① 전 시장(유가·코스닥) 최근 sweep_days일 목록 → 마스터에 있는 상장사 공시 전부.
    ② 대상 기업 중 이력 수집 표시가 없는 곳만 1년 이력(최대 300건) — 다 받은 뒤에만 표시한다."""
    from services.cache_service import is_cached, set_cache
    known = {r[0] for r in conn.execute("SELECT corp_code FROM companies WHERE stock_code IS NOT NULL AND stock_code != ''")}
    stats = {"swept": 0, "history_companies": 0, "inserted": 0, "failed": 0}
    end, bgn = today.strftime("%Y%m%d"), (today - timedelta(days=sweep_days)).strftime("%Y%m%d")
    try:
        for cls in ("Y", "K"):
            try:
                for items in _list_pages(client, {"bgn_de": bgn, "end_de": end, "corp_cls": cls}):
                    stats["swept"] += len(items)
                    stats["inserted"] += _store_disclosures(conn, items, known)
            except DartRequestError:
                stats["failed"] += 1
        hist_bgn = (today - timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d")
        for t in tgts:
            key = f"krdisc:history:{t['corp_code']}"
            if is_cached(key):
                continue
            try:
                for items in _list_pages(client, {"corp_code": t["corp_code"], "bgn_de": hist_bgn, "end_de": end},
                                         HISTORY_PAGES):
                    stats["inserted"] += _store_disclosures(conn, items)
            except DartRequestError:
                stats["failed"] += 1
                continue
            set_cache(key, 3650 * 86400)   # 이력은 한 번이면 된다 — 이후는 ① 전 시장 목록이 잇는다
            stats["history_companies"] += 1
    except BudgetExhausted:
        stats["budget_exhausted"] = 1
    except DartFatal as e:
        stats.update(status="error", reason=str(e))
    if "status" not in stats and stats["failed"]:
        stats["status"] = "partial"
    stats["calls"] = client.calls
    return stats


# ── 분기 재무제표 ─────────────────────────────────────────────────────────

def due_periods(today: date, years: int = FIN_YEARS) -> list[tuple[int, str]]:
    """제출이 시작됐을 (연도, 보고서) — 최신부터. 예산이 끊겨도 최근 분기가 먼저 찬다.
    기간 말일 뒤 FILING_LAG일(분기 30·연간 60, 법정 기한 45·90일보다 앞)부터 묻는다 — 더 일찍 물으면 대상 전부가 013이다."""
    out = []
    for year in range(today.year, today.year - years - 1, -1):
        for rc, m, d in reversed(REPORTS):
            if date(year, m, d) + timedelta(days=FILING_LAG[rc]) < today:
                out.append((year, rc))
    return out


def _period_end(year: int, rc: str) -> date:
    m, d = next((m, d) for code, m, d in REPORTS if code == rc)
    return date(year, m, d)


def missing_periods(conn, corp: str, today: date, years: int = FIN_YEARS) -> list[tuple[int, str]]:
    from services.cache_service import is_cached
    have = {(r[0], r[1]) for r in conn.execute(
        "SELECT DISTINCT bsns_year, reprt_code FROM financial_statements WHERE corp_code=?", (corp,))}
    return [p for p in due_periods(today, years)
            if p not in have and not is_cached(f"krfin:none:{corp}:{p[0]}:{p[1]}")]


def collect_financials(conn, client: DartClient, tgts: list[dict], today: date, years: int = FIN_YEARS) -> dict:
    """대상 순서대로 빠진 기간만 fnlttSinglAcntAll(CFS → 없으면 OFS)로 받아 원본 저장."""
    import pandas as pd
    from services.cache_service import set_cache
    from services.dart_service import _store_financial_df

    stats = {"targets": len(tgts), "periods_added": 0, "rows": 0, "no_data": 0, "failed": 0, "companies_checked": 0}
    try:
        for i, t in enumerate(tgts):
            corp = t["corp_code"]
            for year, rc in missing_periods(conn, corp, today, years):
                got = False
                try:
                    for fs_div in ("CFS", "OFS"):
                        body = client.json("fnlttSinglAcntAll.json",
                                           {"corp_code": corp, "bsns_year": str(year), "reprt_code": rc, "fs_div": fs_div})
                        status = str(body.get("status"))
                        if status == "000" and body.get("list"):
                            before = conn.total_changes
                            _store_financial_df(corp, year, rc, fs_div, pd.DataFrame(body["list"]),
                                                connection=conn, only_missing=True)
                            conn.commit()
                            stats["rows"] += conn.total_changes - before
                            stats["periods_added"] += 1
                            got = True
                            break
                        if status not in ("000", "013"):
                            raise DartRequestError(f"finstate status {status}")
                except DartRequestError:
                    stats["failed"] += 1
                    continue
                if not got:
                    # 미공시 기간(신규 상장 전·제출 기한 전). 기한이 한참 지났으면 오래, 아니면 곧 다시 본다.
                    late = today > _period_end(year, rc) + timedelta(days=120)
                    set_cache(f"krfin:none:{corp}:{year}:{rc}", (60 if late else 3) * 86400)
                    stats["no_data"] += 1
            stats["companies_checked"] += 1
    except BudgetExhausted:
        stats["budget_exhausted"] = 1
        stats["remaining_periods"] = sum(len(missing_periods(conn, t["corp_code"], today, years)) for t in tgts[i:])
    except DartFatal as e:
        stats.update(status="error", reason=str(e))
    if "status" not in stats and stats["failed"]:
        stats["status"] = "partial"
    stats["calls"] = client.calls
    return stats
