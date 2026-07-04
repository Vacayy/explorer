"""Consensus estimate scraper — Naver Finance (navercomp.wisereport.co.kr).

Data structure:
- Table 0: Header with basic info (EPS, BPS, PER, PBR from latest fiscal)
- Table 5: 주요지표 — PER/PBR/EPS/BPS actual + estimate by fiscal year
- Table 11: 투자의견 consensus (opinion, target price, EPS, PER, analyst count)
- Table 12: 증권사별 목표가 breakdown
"""
import re
from database import get_connection
from services.cache_service import is_cached, set_cache

CACHE_TTL = 86400 * 3  # 3 days
BASE_URL = "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx"


def fetch_consensus(stock_code: str) -> dict:
    """Fetch and cache consensus estimates for a stock."""
    cache_key = f"consensus:{stock_code}"

    if not is_cached(cache_key):
        _scrape_naver(stock_code)
        set_cache(cache_key, CACHE_TTL)

    conn = get_connection()
    rows = conn.execute(
        """SELECT fiscal_year, revenue_est, op_profit_est, net_income_est,
                  eps_est, bps_est, per_est, target_price, analyst_count, opinion
           FROM consensus WHERE stock_code = ? ORDER BY fiscal_year""",
        (stock_code,),
    ).fetchall()
    conn.close()

    return {
        "stock_code": stock_code,
        "estimates": [dict(r) for r in rows],
    }


def _scrape_naver(stock_code: str):
    """Scrape Naver Finance consensus data."""
    url = f"{BASE_URL}?cmp_cd={stock_code}"

    try:
        import httpx
        from bs4 import BeautifulSoup
        resp = httpx.get(url, timeout=15, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        })
        resp.raise_for_status()
    except Exception as e:
        print(f"Naver scrape failed for {stock_code}: {e}")
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    conn = get_connection()
    tables = soup.find_all("table")

    # ── 1. Parse 주요지표 table (PER/PBR/EPS/BPS by fiscal year) ──
    for table in tables:
        first_cells = [c.get_text(strip=True) for c in table.find_all(["th", "td"])[:5]]
        if "주요지표" not in first_cells:
            continue

        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Header row: 주요지표, YYYY/MM(A), YYYY/MM(E), ...
        header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        year_cols = []
        for h in header_cells[1:]:  # skip "주요지표"
            is_est = "(E)" in h
            match = re.search(r"(\d{4})/(\d{2})", h)
            if match:
                year = match.group(1)
                year_cols.append(year + ("E" if is_est else ""))

        if not year_cols:
            continue

        # Parse data rows
        metrics: dict[str, dict[str, float | None]] = {y: {} for y in year_cols}
        field_map = {
            "PER": "per_est",
            "PBR": "pbr_est",
            "EPS": "eps_est",
            "BPS": "bps_est",
            "EBITDA": "ebitda_est",
        }

        for tr in rows[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue

            label = cells[0]
            field = field_map.get(label)
            if not field:
                continue

            for i, year_key in enumerate(year_cols):
                if i + 1 < len(cells):
                    val = _parse_num(cells[i + 1])
                    if val is not None:
                        metrics[year_key][field] = val

        # Store estimate years
        for year_key, m in metrics.items():
            if not year_key.endswith("E") or not m:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO consensus
                   (stock_code, data_source, fiscal_year, eps_est, bps_est, per_est)
                   VALUES (?, 'naver', ?, ?, ?, ?)""",
                (stock_code, year_key,
                 m.get("eps_est"), m.get("bps_est"), m.get("per_est")),
            )
        break

    # ── 2. Parse 투자의견 consensus table ──
    target_price = None
    consensus_eps = None
    consensus_per = None
    analyst_count = None
    opinion = None

    for table in tables:
        cells = [c.get_text(strip=True) for c in table.find_all(["th", "td"])]
        if "투자의견" in cells and "목표주가(원)" in cells and "추정기관수" in cells:
            # Row structure: [score, "투자의견", "목표주가(원)", "EPS(원)", "PER(배)", "추정기관수"]
            # Next row:      [score, target_price, eps, per, count]
            try:
                rows = table.find_all("tr")
                if len(rows) >= 2:
                    data_cells = [c.get_text(strip=True) for c in rows[1].find_all(["td", "th"])]
                    if len(data_cells) >= 5:
                        opinion_score = _parse_num(data_cells[0])
                        opinion = f"{opinion_score:.1f}" if opinion_score else None
                        target_price = _parse_num(data_cells[1])
                        consensus_eps = _parse_num(data_cells[2])
                        consensus_per = _parse_num(data_cells[3])
                        analyst_count = _parse_int(data_cells[4])
            except Exception:
                pass
            break

    # Update estimate rows with opinion data
    if any([target_price, consensus_eps, consensus_per, analyst_count]):
        # Get the first estimate year
        est_row = conn.execute(
            """SELECT fiscal_year FROM consensus
               WHERE stock_code = ? AND fiscal_year LIKE '%E'
               ORDER BY fiscal_year ASC LIMIT 1""",
            (stock_code,),
        ).fetchone()

        if est_row:
            conn.execute(
                """UPDATE consensus SET
                     target_price = COALESCE(?, target_price),
                     analyst_count = COALESCE(?, analyst_count),
                     opinion = COALESCE(?, opinion),
                     eps_est = COALESCE(eps_est, ?),
                     per_est = COALESCE(per_est, ?)
                   WHERE stock_code = ? AND fiscal_year = ?""",
                (target_price, analyst_count, opinion, consensus_eps, consensus_per,
                 stock_code, est_row["fiscal_year"]),
            )
        else:
            # No estimate year in DB yet — create one
            import datetime
            next_year = str(datetime.datetime.now().year) + "E"
            conn.execute(
                """INSERT OR REPLACE INTO consensus
                   (stock_code, data_source, fiscal_year, eps_est, per_est,
                    target_price, analyst_count, opinion)
                   VALUES (?, 'naver', ?, ?, ?, ?, ?, ?)""",
                (stock_code, next_year, consensus_eps, consensus_per,
                 target_price, analyst_count, opinion),
            )

    conn.commit()
    conn.close()


def _parse_num(s: str) -> float | None:
    """Parse number from string like '1,405원' or '50.88'."""
    if not s:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", s.replace(",", ""))
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int(s: str) -> int | None:
    n = _parse_num(s)
    return int(n) if n is not None else None
