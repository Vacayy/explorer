"""KSIC 섹터(165) → 투자 언어 대분류 매핑 시드 (1회성, opus 큐레이션).

'특수 목적용 기계 제조업' 같은 통계청 언어를 '반도체·장비' 같은 투자 언어
대분류 ~18개로 접는다 — 섹터 맵(RS 4사분면)의 그룹 축.

사용법: python scripts/seed_sector_map.py [--dry]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.enrich import _claude_bin

GROUPS = [
    "반도체·전자부품", "IT서비스·SW", "바이오·헬스케어", "자동차·모빌리티",
    "2차전지·에너지소재", "전력·에너지", "금융", "화학·소재", "철강·금속",
    "기계·장비", "조선·해운·운송", "건설·부동산", "유통·소비재", "음식료·농수산",
    "미디어·엔터·게임", "통신", "항공·방산·우주", "지주·기타",
]


def main(dry: bool):
    init_db()
    conn = get_connection()
    sectors = [r["name"] for r in conn.execute("""
        SELECT DISTINCT e.name FROM entities e
        JOIN entity_relations er ON er.dst_id = e.id AND er.rel_type='MEMBER_OF'
        WHERE e.type='sector' ORDER BY e.name""")]
    print(f"[seed] KSIC 섹터 {len(sectors)}개 → 대분류 {len(GROUPS)}개 매핑")

    prompt = (
        "한국 표준산업분류(KSIC) 섹터명들을 투자자 언어의 대분류로 매핑해라.\n"
        f"대분류 (이 목록만 사용, 새 이름 금지): {json.dumps(GROUPS, ensure_ascii=False)}\n"
        '출력: JSON만. {"map": {"KSIC명": "대분류", ...}} — 입력된 모든 섹터를 빠짐없이.\n'
        "판단 기준: 그 섹터 상장사들이 투자 맥락에서 어느 그룹으로 묶이는가. "
        "애매하면 주력 산업 기준, 정말 안 맞으면 '지주·기타'.\n\n"
        f"[KSIC 섹터]\n{json.dumps(sectors, ensure_ascii=False)}"
    )
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", "opus", "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[:300])
    raw = json.loads(proc.stdout).get("result", "")
    s, e = raw.find("{"), raw.rfind("}")
    mapping = json.loads(raw[s:e + 1])["map"]

    missing = [x for x in sectors if x not in mapping]
    bad = {k: v for k, v in mapping.items() if v not in GROUPS}
    print(f"[seed] 매핑 {len(mapping)}개 · 누락 {len(missing)} · 목록 외 대분류 {len(bad)}")
    for m in missing:
        mapping[m] = "지주·기타"
    for k in bad:
        mapping[k] = "지주·기타"

    if dry:
        from collections import Counter
        print(Counter(mapping.values()).most_common())
        return
    for k, v in mapping.items():
        conn.execute("INSERT OR REPLACE INTO sector_map (sector_name, group_name) VALUES (?, ?)", (k, v))
    conn.commit()
    n = conn.execute("SELECT count(*) FROM sector_map").fetchone()[0]
    print(f"[seed] 저장 완료: {n}행")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    main(ap.parse_args().dry)
