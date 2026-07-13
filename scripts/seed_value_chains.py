"""대분류별 밸류체인 구조 시드 (opus 큐레이션, 1회성).

참고 이미지 형태: 반도체 = 설계 → 파운드리 → 전공정 → 후공정 → 기판/패키징,
각 단계에 테마(DRAM·HBM·EUV…). 이 구조는 시장 상식이라 LLM 지식으로 생성 가능.
테마 칩은 피드 검색어로 연결 (topic 엔티티와 별개 — 산업 개념).

사용법: python scripts/seed_value_chains.py [group] [--dry]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.enrich import _claude_bin


def seed_group(conn, group: str, dry: bool):
    prompt = (
        f"한국 주식시장 관점에서 '{group}' 산업의 밸류체인을 단계별로 정리해라.\n"
        "왼쪽(상류·소재/설계)에서 오른쪽(하류·완제품/응용)으로 3~5개 단계, "
        "각 단계에 투자자가 쓰는 테마 키워드 2~7개.\n"
        "예: 반도체 = 설계(팹리스·IP·NPU) → 파운드리 → 전공정(장비·소재·가스) → "
        "후공정(패키징·테스트) → 기판/패키징(기판·SOCAMM).\n"
        '출력: JSON만. {"stages": [{"name": "단계명", "themes": ["테마", ...]}, ...]}\n'
        "테마는 실제 시장에서 통용되는 이름으로 (예: HBM, DRAM, 전고체 배터리, 휴머노이드). "
        "종목명 말고 테마·하위산업 수준."
    )
    proc = subprocess.run(
        [_claude_bin(), "-p", "--model", "opus", "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        print(f"  [{group}] 실패: {proc.stderr[:120]}")
        return 0
    raw = json.loads(proc.stdout).get("result", "")
    s, e = raw.find("{"), raw.rfind("}")
    stages = json.loads(raw[s:e + 1]).get("stages", [])
    if dry:
        for i, st in enumerate(stages):
            print(f"  {i}. {st['name']}: {', '.join(st['themes'])}")
        return len(stages)
    conn.execute("DELETE FROM value_chains WHERE group_name=?", (group,))
    for i, st in enumerate(stages):
        conn.execute("""
            INSERT INTO value_chains (group_name, stage_idx, stage_name, themes_json)
            VALUES (?, ?, ?, ?)""",
            (group, i, st["name"], json.dumps(st["themes"], ensure_ascii=False)))
    conn.commit()
    return len(stages)


def main(only: str | None, dry: bool):
    init_db()
    conn = get_connection()
    groups = [only] if only else [r["group_name"] for r in conn.execute(
        "SELECT DISTINCT group_name FROM sector_map ORDER BY group_name")]
    for g in groups:
        n = seed_group(conn, g, dry)
        print(f"[seed] {g}: {n}단계")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("group", nargs="?")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    main(a.group, a.dry)
