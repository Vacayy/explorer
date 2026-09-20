"""Trusted, bounded preparation for an explicit company-research action.

This module is never exposed to CodeAct and never runs from a GET. It can only
insert missing DART rows for one validated company. Provider receipts live in
the discovery directory, separately from source data and immutable run packets.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
MAX_REQUESTS = 30
MAX_SECONDS = 90
MAX_DISCLOSURE_PAGES = 3
MAX_RESPONSE_BYTES = 5_000_000
REPORT_MONTHS = {"11013": 3, "11012": 6, "11014": 9, "11011": 12}


class PreparationCancelled(RuntimeError):
    pass


class PreparationError(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def pending_preparation():
    return {"status": "pending", "items": [
        {"id": "financials", "label": "재무제표", "status": "pending", "detail": "최근 3개 연도와 분기 자료를 확인합니다."},
        {"id": "disclosures", "label": "최근 공시", "status": "pending", "detail": "최근 1년의 공시 목록을 확인합니다."},
        {"id": "call", "label": "IR·컨퍼런스콜", "status": "unsupported", "detail": "국내 기업의 자동 수집 경로가 없습니다. 기존 저장 원문은 조사에 활용합니다."},
        {"id": "trade", "label": "수출입 통계", "status": "unsupported", "detail": "기업·품목 연결의 확인이 필요합니다. 기존 통계와 연결 근거를 읽습니다."},
        {"id": "web", "label": "웹 조사 · 사업보고서·IR·뉴스·리포트", "status": "pending", "detail": "자료 준비 뒤 웹에서 기업 개요와 최근 사건의 발췌를 확보합니다."},
    ]}


def report_periods(today: date):
    """Three annual reports and recent quarters, including CF prerequisites.

    These are conservative collection windows, not asserted filing deadlines.
    An official 013 response remains explicitly 'not returned', not proof that
    a company has not published any financial information elsewhere.
    """
    result = []
    for year in range(today.year - 3, today.year + 1):
        for code, month in REPORT_MONTHS.items():
            if year == today.year - 3 and month != 12:
                continue
            end = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
            if end + timedelta(days=90 if month == 12 else 45) <= today:
                result.append((year, code))
    return sorted(result, key=lambda value: (value[0], REPORT_MONTHS[value[1]]), reverse=True)


class ReceiptCache:
    """Only validated success / official no-data responses enter this cache.

    Append-only receipts retain acquisition timing and provider payloads. The
    cache has a new namespace, so old failures cached as success cannot block
    missing-data retries. Neither keys nor payloads contain API credentials.
    """
    def __init__(self, root: Path):
        self.path = root / "preparation.sqlite"
        if self.path.is_symlink() or (self.path.exists() and self.path.stat().st_nlink != 1):
            raise PreparationError("자료 준비 기록 경로를 사용할 수 없습니다.")
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS receipts(
                    id INTEGER PRIMARY KEY, cache_key TEXT NOT NULL,
                    acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS receipt_key ON receipts(cache_key, id DESC);
            """)

    def is_cached(self, key, *, include_expired=False):
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute("SELECT acquired_at,expires_at,body FROM receipts WHERE cache_key=? ORDER BY id DESC LIMIT 1", (key,)).fetchone()
        if row and (include_expired or datetime.fromisoformat(row[1]) > datetime.now(timezone.utc)):
            return json.loads(row[2]), row[0]
        return None

    def set_cache(self, key, body, seconds):
        acquired = now()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("INSERT INTO receipts(cache_key,acquired_at,expires_at,body) VALUES (?,?,?,?)",
                         (key, acquired, (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(),
                          json.dumps(body, ensure_ascii=False, allow_nan=False)))
            conn.commit()
        return acquired


class DartClient:
    """Fixed official endpoints, bounded time/bytes; sanitized failures only."""
    def __init__(self, key, cancel, deadline):
        self.key, self.cancel, self.deadline = key, cancel, deadline
        self.requests = 0

    def get(self, endpoint, params):
        import requests
        if endpoint not in {"fnlttSinglAcntAll.json", "list.json"}:
            raise PreparationError("허용되지 않은 자료원입니다.")
        if self.cancel():
            raise PreparationCancelled()
        remaining = self.deadline - time.monotonic()
        if self.requests >= MAX_REQUESTS or remaining < 1:
            raise PreparationError("이번 자료 준비의 시간·요청 한도에 도달했습니다. 확보한 자료로 조사를 계속합니다.")
        self.requests += 1
        try:
            with requests.get("https://opendart.fss.or.kr/api/" + endpoint,
                              params={**params, "crtfc_key": self.key}, timeout=(min(5, remaining), min(10, remaining)),
                              stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise PreparationError(f"DART 응답 오류(HTTP {response.status_code}). 다음 조사에서 다시 확인할 수 있습니다.")
                content = bytearray()
                for chunk in response.iter_content(65536):
                    if self.cancel():
                        raise PreparationCancelled()
                    if time.monotonic() > self.deadline:
                        raise PreparationError("자료 준비의 시간 한도를 초과했습니다.")
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise PreparationError("DART 응답이 허용 크기를 초과했습니다.")
                body = json.loads(content)
        except requests.RequestException:
            # RequestException may contain the URL with crtfc_key. Never expose it.
            raise PreparationError("DART 연결에 실패했습니다. 다음 조사에서 다시 확인할 수 있습니다.") from None
        except (ValueError, TypeError):
            raise PreparationError("DART 응답 형식을 확인하지 못했습니다.") from None
        if not isinstance(body, dict):
            raise PreparationError("DART 응답 형식이 올바르지 않습니다.")
        status = body.get("status")
        if status not in {"000", "013"}:
            reason = {"010": "인증 설정", "011": "인증 설정", "012": "접근 권한", "901": "인증 설정",
                      "020": "요청 한도", "800": "서비스 점검"}.get(status, "자료원 응답")
            raise PreparationError(f"DART {reason} 문제로 수집하지 못했습니다. 실패를 완료로 캐시하지 않았습니다.")
        if status == "000" and (not isinstance(body.get("list"), list) or not body["list"]):
            raise PreparationError("DART 정상 응답에 자료 목록이 없습니다.")
        return body


@contextmanager
def company_lock(root, code, check):
    fd = os.open(root / f"preparation-{code}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        while True:
            check()
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def _connection(path, *, write=False):
    # mode=rw refuses to silently create a missing source database.
    conn = sqlite3.connect(path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    if not write:
        conn.execute("PRAGMA query_only=ON")
    return conn


def _validate_financial(body, corp, year, report, basis, today):
    if body["status"] == "013":
        return []
    rows = body["list"]
    if len(rows) > 3000:
        raise PreparationError("재무 응답의 계정 수가 허용 범위를 초과했습니다.")
    accepted = []
    for row in rows:
        if (not isinstance(row, dict) or row.get("corp_code") != corp
                or str(row.get("bsns_year")) != str(year) or row.get("reprt_code") != report
                or (row.get("fs_div") is not None and row["fs_div"] != basis)):
            raise PreparationError("요청 기업·기간과 다른 재무 자료를 거부했습니다.")
        receipt = str(row.get("rcept_no", ""))
        if not re.fullmatch(r"\d{14}", receipt):
            raise PreparationError("재무 자료의 접수번호를 확인하지 못했습니다.")
        try:
            published = datetime.strptime(receipt[:8], "%Y%m%d").date()
        except ValueError:
            raise PreparationError("재무 자료의 접수일이 올바르지 않습니다.") from None
        if published > today:
            raise PreparationError("미래 접수일을 가진 재무 자료를 거부했습니다.")
        if row.get("sj_div") not in {"IS", "CIS", "BS", "CF"}:
            continue
        if row.get("currency") not in (None, "", "KRW"):
            raise PreparationError("원화가 아닌 재무 자료는 자동 적재하지 않습니다.")
        if not isinstance(row.get("account_nm"), str) or not 0 < len(row["account_nm"]) <= 500:
            raise PreparationError("재무 계정명이 올바르지 않습니다.")
        for field in ("thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount"):
            value = row.get(field)
            if value not in (None, "", "-") and not re.fullmatch(r"-?[\d,]+(?:\.\d+)?", str(value).strip()):
                raise PreparationError("재무 금액 형식을 확인하지 못했습니다.")
        accepted.append(row)
    if not accepted:
        raise PreparationError("사용 가능한 손익·재무상태·현금흐름 계정이 없습니다.")
    return accepted


def _validate_disclosures(body, corp, begin, end):
    if body["status"] == "013":
        return []
    if len(body["list"]) > 100:
        raise PreparationError("공시 목록 크기가 허용 범위를 초과했습니다.")
    for row in body["list"]:
        if (not isinstance(row, dict) or row.get("corp_code") != corp
                or not re.fullmatch(r"\d{14}", str(row.get("rcept_no", "")))
                or not re.fullmatch(r"\d{8}", str(row.get("rcept_dt", "")))
                or not begin <= row["rcept_dt"] <= end):
            raise PreparationError("요청 기업·기간과 다른 공시 자료를 거부했습니다.")
    return body["list"]


def prepare_company(source_db, root, case, *, as_of=None, progress=None, cancel=lambda: False,
                    client_factory=DartClient, today=None):
    """Returns persistent progress; collection failures degrade research, not data."""
    today = today or datetime.now(SEOUL).date()
    state = pending_preparation()
    state.update(status="running", started_at=now(), financial_reports=[], requests=0)
    items = {item["id"]: item for item in state["items"]}
    deadline = time.monotonic() + MAX_SECONDS

    def publish(identifier=None, status=None, detail=None):
        if identifier:
            items[identifier].update(status=status, detail=detail)
        if progress:
            progress(copy.deepcopy(state))

    def check():
        if cancel():
            raise PreparationCancelled()
        if time.monotonic() >= deadline:
            raise PreparationError("자료 준비의 시간 한도에 도달했습니다.")

    def finish():
        state.update(status="partial" if any(i["status"] in {"failed", "unpublished", "unsupported"} for i in items.values()) else "completed",
                     completed_at=now())
        publish()
        return state

    publish()
    try:
        check()
        if as_of and date.fromisoformat(as_of) < today:
            detail = "과거 시점 조사에서는 새 수집을 생략합니다. 당시 확보 여부를 확인할 수 있는 저장 자료만 읽습니다."
            publish("financials", "unsupported", detail)
            publish("disclosures", "unsupported", detail)
            return finish()
        code = str(case.get("stock_code") or "")
        if not re.fullmatch(r"[0-9A-Z]{6}", code):
            raise PreparationError("국내 종목코드의 자료만 자동 수집할 수 있습니다.")
        path = Path(source_db).resolve(strict=True)
        with closing(_connection(path)) as conn:
            row = conn.execute("SELECT corp_code FROM companies WHERE stock_code=? LIMIT 1", (code,)).fetchone()
        if row is None or not re.fullmatch(r"\d{8}", str(row["corp_code"])):
            for identifier in ("financials", "disclosures"):
                publish(identifier, "unsupported", "이 기업의 유효한 DART 식별자를 확인하지 못했습니다. 기존 자료로 조사를 계속합니다.")
            return finish()
        corp = row["corp_code"]
        with company_lock(Path(root), code, check):
            from config import DART_API_KEY
            cache = ReceiptCache(Path(root))
            client = client_factory(DART_API_KEY, cancel, deadline)

            def request(endpoint, params, validate):
                check()
                key = "dart-v1:" + hashlib.sha256(json.dumps([endpoint, params], sort_keys=True).encode()).hexdigest()
                cached = cache.is_cached(key)
                if cached:
                    body, acquired = cached
                    return body, validate(body), acquired, True
                if not DART_API_KEY:
                    raise PreparationError("DART 인증 설정이 없어 수집하지 못했습니다. 기존 자료로 조사를 계속합니다.")
                body = client.get(endpoint, params)
                check()
                rows = validate(body)
                # Official no-data gets a short TTL; network/auth/quota failures never do.
                acquired = cache.set_cache(key, body, 6 * 3600 if body["status"] == "013" else 24 * 3600)
                state["requests"] = client.requests
                return body, rows, acquired, False

            publish("financials", "checking", "저장된 손익·재무상태·현금흐름 자료의 기간과 연결 기준을 확인합니다.")
            added = covered = missing = 0
            periods = report_periods(today)
            try:
                for index, (year, report) in enumerate(periods):
                    check()
                    month = REPORT_MONTHS[report]
                    with closing(_connection(path)) as conn:
                        present = conn.execute("SELECT fs_div,sj_div FROM financial_statements WHERE corp_code=? AND bsns_year=? AND reprt_code=? GROUP BY fs_div,sj_div", (corp, year, report)).fetchall()
                    categories = {r["sj_div"] for r in present if r["fs_div"] == "CFS"}
                    if "BS" in categories and "CF" in categories and categories & {"IS", "CIS"}:
                        covered += 1
                        # Keep known receipt provenance on later research runs
                        # even when no collection is needed. An old receipt is
                        # never represented as a fresh check or a historical version.
                        params = {"corp_code": corp, "bsns_year": str(year), "reprt_code": report, "fs_div": "CFS"}
                        key = "dart-v1:" + hashlib.sha256(json.dumps(["fnlttSinglAcntAll.json", params], sort_keys=True).encode()).hexdigest()
                        prior = cache.is_cached(key, include_expired=True)
                        if prior and prior[0]["status"] == "000":
                            receipts = sorted({r["rcept_no"] for r in prior[0]["list"]})
                            state["financial_reports"].append({"year": year, "report_code": report, "month": month, "basis": "CFS",
                                "receipt_numbers": receipts, "receipt_dates": [f"{r[:4]}-{r[4:6]}-{r[6:8]}" for r in receipts],
                                "fetched_at": prior[1], "unit": "KRW", "source": "DART fnlttSinglAcntAll", "inserted_rows": 0,
                                "all_rows_new": False, "existing_rows_preserved": True, "reused_response": True})
                        continue
                    publish("financials", "collecting", f"{year}년 {month}월 보고서 확인 중 · {index + 1}/{len(periods)}개 기간")
                    for basis in ("CFS", "OFS"):
                        body, rows, acquired, cached = request("fnlttSinglAcntAll.json",
                            {"corp_code": corp, "bsns_year": str(year), "reprt_code": report, "fs_div": basis},
                            lambda body: _validate_financial(body, corp, year, report, basis, today))
                        if body["status"] == "013":
                            if basis == "OFS":
                                missing += 1
                            continue
                        import pandas as pd
                        from services.dart_service import _store_financial_df
                        check()
                        with closing(_connection(path, write=True)) as conn:
                            with conn:
                                check()
                                before = conn.total_changes
                                _store_financial_df(corp, year, report, basis, pd.DataFrame(rows), connection=conn, only_missing=True)
                                count = conn.total_changes - before
                                check()
                        added += count
                        covered += 1
                        receipts = sorted({r["rcept_no"] for r in rows})
                        state["financial_reports"].append({"year": year, "report_code": report, "month": month, "basis": basis,
                            "receipt_numbers": receipts, "receipt_dates": [f"{r[:4]}-{r[4:6]}-{r[6:8]}" for r in receipts],
                            "fetched_at": acquired, "unit": "KRW", "source": "DART fnlttSinglAcntAll", "inserted_rows": count,
                            "response_rows": len(rows), "all_rows_new": count == len(rows),
                            "existing_rows_preserved": True, "reused_response": cached})
                        break
                detail = f"{len(periods)}개 기간 중 {covered}개 확보 · 새 계정 {added}개. 기존 수치는 보존했으며 최신 정정 여부는 확인하지 않았습니다."
                if missing:
                    detail += f" {missing}개 기간은 DART에서 자료를 반환하지 않았습니다(미공개·제공 범위 미포함 가능)."
                publish("financials", "collected" if added else "available" if covered else "unpublished", detail)
            except PreparationError as exc:
                publish("financials", "failed", f"{exc} 확보한 기간 {covered}개 · 새 계정 {added}개.")

            publish("disclosures", "checking", "최근 1년의 접수 공시를 확인합니다.")
            begin, end = (today - timedelta(days=365)).strftime("%Y%m%d"), today.strftime("%Y%m%d")
            disclosure_count = 0
            try:
                total_pages = 1
                inserted = 0
                for page in range(1, MAX_DISCLOSURE_PAGES + 1):
                    publish("disclosures", "collecting", f"최근 공시 목록 {page}페이지 확인 중")
                    body, rows, acquired, cached = request("list.json", {"corp_code": corp, "bgn_de": begin,
                        "end_de": end, "page_no": str(page), "page_count": "100", "sort": "date", "sort_mth": "desc"},
                        lambda body: _validate_disclosures(body, corp, begin, end))
                    if body["status"] == "013":
                        break
                    check()
                    with closing(_connection(path, write=True)) as conn:
                        with conn:
                            before = conn.total_changes
                            for row in rows:
                                conn.execute("""INSERT OR IGNORE INTO disclosures
                                    (rcp_no,corp_code,corp_name,report_nm,rcept_dt,flr_nm,rm,kind,dart_url)
                                    VALUES (?,?,?,?,?,?,?,?,?)""", (row["rcept_no"], corp, row.get("corp_name", ""),
                                    row.get("report_nm", ""), row["rcept_dt"], row.get("flr_nm", ""), row.get("rm", ""), "",
                                    "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + row["rcept_no"]))
                            check()
                            inserted += conn.total_changes - before
                    disclosure_count += len(rows)
                    total_pages = int(body.get("total_page", 1))
                    if page >= total_pages:
                        break
                detail = f"공시 제목·접수일 {disclosure_count}건 확인 · 새 공시 {inserted}건. 공시 전문은 포함하지 않습니다."
                if total_pages > MAX_DISCLOSURE_PAGES:
                    detail += " 최신 300건 한도로 일부 목록만 확보했습니다."
                publish("disclosures", "collected" if inserted else "available" if disclosure_count else "unpublished", detail)
            except PreparationError as exc:
                publish("disclosures", "failed", str(exc))
        return finish()
    except PreparationCancelled:
        state.update(status="cancelled", completed_at=now())
        publish()
        raise
    except (PreparationError, OSError, sqlite3.Error, ValueError) as exc:
        # Never include arbitrary provider exceptions/URLs here.
        detail = str(exc) if isinstance(exc, PreparationError) else "저장 자료의 준비 과정에 오류가 있습니다. 기존 자료로 조사를 계속합니다."
        for identifier in ("financials", "disclosures"):
            if items[identifier]["status"] in {"pending", "checking", "collecting"}:
                publish(identifier, "failed", detail)
        return finish()
