"""전종목 밸류 지표 수집 — 네이버 금융 시세 페이지 (PER·ROE·시총).

pykrx fundamental이 KRX 로그인 벽에 막혀 있어(세션 재확인 완료) 네이버 시세
테이블을 대체 소스로 사용 (컨센서스 스크레이퍼와 같은 계열). 일 1회면 충분.
저장: fundamentals(stock_code, trade_date, per, roe) — 기존 테이블 재사용.
"""
import time
from datetime import date

import httpx
from bs4 import BeautifulSoup

from database import get_connection

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _num(s: str) -> float | None:
    s = (s or "").replace(",", "").strip()
    if not s or s in ("N/A", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_market_valuation() -> dict:
    """KOSPI+KOSDAQ 전종목 PER·ROE 수집 → fundamentals upsert. 반환: 통계."""
    today = date.today().isoformat()
    conn = get_connection()
    total = 0
    with httpx.Client(timeout=15, headers=_HEADERS) as client:
        for sosok in (0, 1):  # 0=KOSPI, 1=KOSDAQ
            for page in range(1, 60):
                r = client.get(
                    f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}")
                soup = BeautifulSoup(r.text, "html.parser")
                rows = [tr for tr in soup.select("table.type_2 tr") if tr.select_one("a.tltle")]
                if not rows:
                    break
                for tr in rows:
                    code = tr.select_one("a.tltle")["href"].split("code=")[-1]
                    tds = [td.get_text(strip=True) for td in tr.select("td")]
                    # [N, 종목명, 현재가, 전일비, 등락률, 액면가, 시총(억), 상장주식수, 외인비율, 거래량, PER, ROE, 토론]
                    if len(tds) < 12:
                        continue
                    per, roe = _num(tds[10]), _num(tds[11])
                    conn.execute("""
                        INSERT INTO fundamentals (stock_code, trade_date, per, roe)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(stock_code, trade_date) DO UPDATE SET
                            per=excluded.per, roe=excluded.roe
                    """, (code, today, per, roe))
                    total += 1
                conn.commit()
                time.sleep(0.2)  # politeness
    conn.close()
    return {"date": today, "stocks": total}
