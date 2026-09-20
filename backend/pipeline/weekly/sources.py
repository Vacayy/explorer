"""Registered acquisitions; raw responses are returned for per-run preservation."""
import ipaddress
import json
import math
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .evidence import instant, observation_bound, publication_bound
from .store import now

OFFICIAL_DOMAINS = ("federalreserve.gov", "bls.gov", "bea.gov", "cftc.gov", "census.gov",
                    "treasury.gov", "sec.gov", "stlouisfed.org", "newyorkfed.org",
                    "investor.oracle.com")
FRED_SERIES = {
    "DGS2": ("2-year Treasury yield", "percent", "yield"),
    "DGS10": ("10-year Treasury yield", "percent", "yield"),
    "WALCL": ("Federal Reserve total assets", "million USD", "level"),
    "WTREGEN": ("Treasury General Account", "million USD", "level"),
    "RRPONTSYD": ("Overnight reverse repo", "billion USD", "level"),
    "M2SL": ("M2 seasonally adjusted", "billion USD", "level"),
    "BAMLH0A0HYM2": ("US high yield option-adjusted spread", "percent", "yield"),
    "VIXCLS": ("VIX close", "index points", "level"),
}


def safe_url(url):
    u = urlsplit(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
        raise ValueError("공식 HTTPS 공개 URL만 허용합니다")
    if not any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS):
        raise ValueError("등록되지 않은 웹 공급자입니다. acquisition gap에 필요한 출처를 기록하세요")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("비공개 네트워크 주소는 읽을 수 없습니다")
    return url


def get_public(url, *, params=None):
    # Recheck redirect destinations; cap raw bytes and do not execute HTML scripts.
    for _ in range(4):
        safe_url(url)
        with requests.get(url, params=params, timeout=(8, 25), allow_redirects=False, stream=True,
                          headers={"User-Agent": "Explorer-Weekly/1.0 (local research reader)"}) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                params = None
                continue
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > 4_000_000:
                    raise ValueError("원문이 4MB 상한을 넘었습니다. 분할 또는 전용 공급자가 필요합니다")
            return bytes(body).decode(response.encoding or "utf-8", errors="replace"), dict(response.headers)
    raise ValueError("공급자 redirect 상한 초과")


def acquire(provider, args, cutoff, mode):
    boundary = instant(cutoff)
    if provider == "fred":
        series = args["series"]
        if series not in FRED_SERIES:
            raise ValueError("지원 FRED 시리즈: " + ", ".join(FRED_SERIES))
        key = os.getenv("FRED_API_KEY")
        if not key:
            raise ValueError("FRED_API_KEY 미설정: 과거 vintage를 현재 CSV 값으로 대체하지 않습니다")
        # ALFRED vintage is date-resolution. Use the previous fully elapsed UTC−12 day.
        vintage = (boundary - timedelta(hours=36)).date().isoformat()
        params = {"series_id": series, "api_key": key, "file_type": "json",
                  "realtime_start": vintage, "realtime_end": vintage,
                  "observation_start": args["start"], "observation_end": args["end"],
                  "units": "lin", "output_type": 1, "limit": 100000}
        raw, headers = get_public("https://api.stlouisfed.org/fred/series/observations", params=params)
        body = json.loads(raw)
        if body.get("count", 0) > len(body.get("observations", [])):
            raise ValueError("FRED 응답이 잘렸습니다")
        points = [{"date": row["date"], "value": float(row["value"]), "raw": row} for row in body.get("observations", [])
                  if row["value"] != "." and row["date"] <= boundary.date().isoformat()]
        title, unit, kind = FRED_SERIES[series]
        return {"kind": "series", "meta": {"title": title, "series": series, "unit": unit,
                "metric_kind": kind, "source_type": "fred", "url": f"https://fred.stlouisfed.org/series/{series}",
                "fetched_at": now(), "vintage": vintage, "time_precision": "date_conservative_bound",
                "temporal_status": "public_vintage_verified", "population": series,
                "warnings": ["cutoff 당일 발표는 날짜 해상도 때문에 보수적으로 제외합니다."]},
                "data": {"points": points, "response": body, "parameters": {k: v for k, v in params.items() if k != "api_key"}}, "text": ""}
    if provider == "yahoo_prices":
        import yfinance as yf
        ticker = args["ticker"]
        if not re.fullmatch(r"[A-Z0-9^.=\-]{1,20}", ticker):
            raise ValueError("잘못된 ticker")
        if args["start"] >= args["end"]:
            raise ValueError("Yahoo 종료일은 exclusive이며 시작일 이후여야 합니다")
        frame = yf.download(ticker, start=args["start"], end=args["end"], auto_adjust=False,
                            actions=True, progress=False, threads=False, timeout=20, multi_level_index=False)
        if frame is None or frame.empty:
            raise ValueError("Yahoo 가격을 확보하지 못했습니다")
        points = []
        for idx, row in frame.iterrows():
            day = idx.date().isoformat()
            # This adapter is explicitly US daily price coverage.
            if observation_bound(day, "us:" + ticker) > boundary:
                continue
            values = {str(k): float(v) if math.isfinite(float(v)) else None for k, v in row.items()}
            if values.get("Close") is None:
                continue
            points.append({"date": day, "value": values["Close"], "volume": values.get("Volume"), "raw": values})
        if not points:
            raise ValueError("cutoff 이전 완료된 가격 관측치가 없습니다")
        return {"kind": "series", "meta": {"title": ticker + " daily close", "series": "us:" + ticker,
                "unit": "USD / share" if not ticker.startswith("^") else "index points", "metric_kind": "price",
                "source_type": "yahoo_prices", "url": f"https://finance.yahoo.com/quote/{ticker}/history/",
                "fetched_at": now(), "population": ticker, "adjustment": "auto_adjust=False; provider split-adjusted Close; Adj Close separately preserved",
                "temporal_status": "captured_live" if mode == "live" else "historical_version_unverified",
                "warnings": ["Yahoo의 현재 과거 가격 버전입니다. 당시 조정 이력·배당 재투자 수익률을 보장하지 않습니다.",
                             "미국 정규장 일별 USD 주식/ETF/지수 전용. 거래소 마감은 보수적인 16:00 NY 상한입니다."]},
                "data": {"points": points, "parameters": args}, "text": ""}
    if provider == "official_page":
        url = args["url"]
        raw, headers = get_public(url)
        if not any(t in headers.get("Content-Type", "").lower() for t in ("text/html", "text/plain", "application/json")):
            raise ValueError("초기 웹 어댑터는 HTML/text/JSON만 지원합니다. PDF·이미지 전용 읽기가 필요합니다")
        soup = BeautifulSoup(raw, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else url
        # Only explicit publisher metadata; no model guessed dates or Last-Modified substitution.
        published = None
        for attrs in ({"property": "article:published_time"}, {"name": "date"}, {"name": "DC.date.issued"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                published = tag["content"]
                break
        bound, precision = publication_bound(published)
        if bound and bound > boundary:
            raise ValueError("공식 페이지 발행일이 cutoff 이후입니다")
        for node in soup(["script", "style", "noscript", "nav", "header", "footer"]):
            node.decompose()
        text = soup.get_text("\n", strip=True)
        if len(text) < 80:
            raise ValueError("읽을 수 있는 웹 원문이 부족합니다")
        return {"kind": "document", "meta": {"title": title, "url": url, "source_type": "official_page",
                "published_at": published, "available_at_bound": bound.isoformat() if bound else None,
                "fetched_at": now(), "time_precision": precision, "content_kind": "html_text",
                "temporal_status": ("captured_live" if mode == "live" and bound else "historical_version_unverified"),
                "warnings": ["웹 원문의 현재 버전입니다. 발행시각 메타데이터가 없으면 cutoff 당시 정보로 확정할 수 없습니다."]},
                "data": {"raw_content": raw, "headers": {k: v for k, v in headers.items() if k.lower() in {"content-type", "last-modified", "etag"}}}, "text": text}
    raise ValueError("등록되지 않은 공급자")
