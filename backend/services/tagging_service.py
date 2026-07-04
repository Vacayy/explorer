"""Auto-tag blog posts by matching keywords in title + summary."""
from database import get_connection

# Normalized tag dictionaries
INDUSTRY_KEYWORDS = {
    "반도체": ["반도체", "메모리", "HBM", "DRAM", "NAND", "파운드리", "웨이퍼", "EUV", "ASML"],
    "2차전지": ["2차전지", "배터리", "양극재", "음극재", "전해질", "분리막", "LFP", "NCM"],
    "자동차": ["자동차", "전기차", "EV", "자율주행", "테슬라", "현대차"],
    "바이오": ["바이오", "제약", "신약", "임상", "FDA"],
    "인터넷/플랫폼": ["네이버", "카카오", "쿠팡", "플랫폼", "이커머스"],
    "방산": ["방산", "방위", "한화에어", "LIG넥스원"],
    "AI": ["AI", "인공지능", "LLM", "GPU", "엔비디아", "NVIDIA"],
    "에너지": ["원유", "가스", "태양광", "풍력", "에너지"],
}

TOPIC_KEYWORDS = {
    "실적분석": ["실적", "매출", "영업이익", "순이익", "어닝", "컨콜", "컨퍼런스콜", "가이던스"],
    "밸류에이션": ["밸류에이션", "PER", "PBR", "목표주가", "적정가치", "DCF"],
    "산업동향": ["산업", "시장", "트렌드", "전망", "수요", "공급", "사이클"],
    "매크로": ["금리", "환율", "인플레이션", "GDP", "연준", "Fed", "BOK"],
    "수급": ["외국인", "기관", "공매도", "수급", "프로그램"],
    "IPO/이벤트": ["IPO", "상장", "유상증자", "합병", "인수", "M&A"],
}


def auto_tag_post(post_id: int, title: str, summary: str = ""):
    """Auto-tag a blog post based on title and summary text."""
    text = f"{title} {summary}".upper()  # Case-insensitive matching

    conn = get_connection()

    # Industry tags
    for tag, keywords in INDUSTRY_KEYWORDS.items():
        if any(kw.upper() in text for kw in keywords):
            conn.execute(
                "INSERT OR IGNORE INTO blog_post_tags (post_id, tag_type, tag_value) VALUES (?, 'industry', ?)",
                (post_id, tag)
            )

    # Topic tags
    for tag, keywords in TOPIC_KEYWORDS.items():
        if any(kw.upper() in text for kw in keywords):
            conn.execute(
                "INSERT OR IGNORE INTO blog_post_tags (post_id, tag_type, tag_value) VALUES (?, 'topic', ?)",
                (post_id, tag)
            )

    # Stock tags — match against companies table
    rows = conn.execute(
        "SELECT stock_code, corp_name FROM companies WHERE stock_code IS NOT NULL"
    ).fetchall()
    for row in rows:
        if row["corp_name"] in title or row["corp_name"] in (summary or ""):
            conn.execute(
                "INSERT OR IGNORE INTO blog_post_tags (post_id, tag_type, tag_value) VALUES (?, 'stock', ?)",
                (post_id, row["stock_code"])
            )

    conn.commit()
    conn.close()


def get_tags_for_posts(post_ids: list[int]) -> dict[int, list[dict]]:
    """Get tags for multiple posts at once."""
    if not post_ids:
        return {}
    conn = get_connection()
    placeholders = ",".join("?" for _ in post_ids)
    rows = conn.execute(
        f"SELECT post_id, tag_type, tag_value FROM blog_post_tags WHERE post_id IN ({placeholders})",
        post_ids
    ).fetchall()
    conn.close()

    result: dict[int, list[dict]] = {pid: [] for pid in post_ids}
    for r in rows:
        result[r["post_id"]].append({"type": r["tag_type"], "value": r["tag_value"]})
    return result


def get_all_tags() -> list[dict]:
    """Get all unique tags with counts."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT tag_type, tag_value, COUNT(*) as count
           FROM blog_post_tags
           GROUP BY tag_type, tag_value
           ORDER BY tag_type, count DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
