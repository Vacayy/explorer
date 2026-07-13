"""AI/반도체 밸류체인 온톨로지 시딩 (1회성) — 세계관 확장 기반.

해외 상장·비상장 핵심 주체와 밸류체인 개념을 엔티티로 미리 등록한다.
문서에서 이들이 언급되는 순간 태깅·팔로우·지식 승격 대상이 되도록 —
enrich가 인식할 어휘의 '앵커'. meta_json에 listed·category·ticker 기록.

사용법: python scripts/seed_ai_ontology.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db

# (한국어 통용 표기, 카테고리, listed, 티커)
COMPANIES = [
    # 빅테크 (해외 상장)
    ("알파벳", "빅테크", "해외", "GOOGL"), ("아마존", "빅테크", "해외", "AMZN"),
    ("애플", "빅테크", "해외", "AAPL"), ("마이크로소프트", "빅테크", "해외", "MSFT"),
    ("메타", "빅테크", "해외", "META"),
    # 소프트웨어 (해외 상장)
    ("오라클", "소프트웨어", "해외", "ORCL"), ("데이터독", "소프트웨어", "해외", "DDOG"),
    ("팔란티어", "소프트웨어", "해외", "PLTR"), ("세일즈포스", "소프트웨어", "해외", "CRM"),
    ("스노우플레이크", "소프트웨어", "해외", "SNOW"), ("서비스나우", "소프트웨어", "해외", "NOW"),
    # 소프트웨어·데이터 (비상장)
    ("데이터브릭스", "소프트웨어", "비상장", None),
    # AI 모델사 (비상장)
    ("오픈AI", "AI모델", "비상장", None), ("앤트로픽", "AI모델", "비상장", None),
    ("xAI", "AI모델", "비상장", None), ("미스트랄", "AI모델", "비상장", None),
    ("퍼플렉시티", "AI모델", "비상장", None), ("SSI", "AI모델", "비상장", None),
    # 비상장 AI 애플리케이션·로보틱스
    ("피규어AI", "비상장AI", "비상장", None), ("하비", "비상장AI", "비상장", None),
    ("힉스필드", "비상장AI", "비상장", None), ("코그니션", "비상장AI", "비상장", None),
    # 컴퓨트·반도체 (해외 상장)
    ("엔비디아", "컴퓨트", "해외", "NVDA"), ("브로드컴", "컴퓨트", "해외", "AVGO"),
    ("AMD", "컴퓨트", "해외", "AMD"), ("마이크론", "컴퓨트", "해외", "MU"),
    ("ARM", "컴퓨트", "해외", "ARM"), ("마벨", "컴퓨트", "해외", "MRVL"),
    ("나비타스", "전력반도체", "해외", "NVTS"),
    # 파운드리
    ("TSMC", "파운드리", "해외", "TSM"), ("인텔", "파운드리", "해외", "INTC"),
    # 반도체 장비 (해외)
    ("ASML", "반도체장비", "해외", "ASML"), ("어플라이드머티어리얼즈", "반도체장비", "해외", "AMAT"),
    ("램리서치", "반도체장비", "해외", "LRCX"), ("KLA", "반도체장비", "해외", "KLAC"),
]

# 밸류체인 개념 (theme) — enrich가 topic으로 인식할 앵커
THEMES = [
    "베라-루빈", "카이버랙", "CPO", "실리콘포토닉스", "어드밴스드 패키징",
    "전력반도체", "SiC", "GaN", "AI 데이터센터", "AI 가속기", "커스텀 ASIC",
    "온디바이스 AI", "휴머노이드", "피지컬 AI", "AI 에이전트", "코딩 에이전트",
]


def main():
    init_db()
    conn = get_connection()
    new_c = upd_c = 0
    for name, cat, listed, ticker in COMPANIES:
        meta = json.dumps({"category": cat, "listed": listed, "ticker": ticker}, ensure_ascii=False)
        row = conn.execute("SELECT id, meta_json FROM entities WHERE type='company' AND name=?",
                           (name,)).fetchone()
        if row:
            if not row["meta_json"] or row["meta_json"] == "{}":
                conn.execute("UPDATE entities SET meta_json=? WHERE id=?", (meta, row["id"]))
                upd_c += 1
        else:
            conn.execute("INSERT INTO entities (type, name, meta_json) VALUES ('company', ?, ?)",
                        (name, meta))
            new_c += 1
    new_t = 0
    for t in THEMES:
        row = conn.execute("SELECT id FROM entities WHERE type='theme' AND name=?", (t,)).fetchone()
        if not row:
            conn.execute("INSERT INTO entities (type, name) VALUES ('theme', ?)", (t,))
            new_t += 1
    conn.commit()
    conn.close()
    print(f"[seed-ai] 기업: 신규 {new_c} · meta보강 {upd_c} / 테마: 신규 {new_t}")


if __name__ == "__main__":
    main()
