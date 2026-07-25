"""effect_strength·effect_direction 백필 (D-065) — 기존 인과 엣지에 '효과 크기·방향'을 소급 추론.

confidence(확신)에 뭉뚱그려져 있던 '효과 크기'를 별도 축으로 떼어낸다(PHILOSOPHY §1).
**additive only**: effect_strength/direction만 채우고 confidence는 건드리지 않는다 —
confidence는 재적재마다 corroboration으로 누적 강화되는 값이라(narrative._persist_causal,
+0.05 cap 0.95) 문맥 없이 재산출하면 교차검증 이력을 뭉갠다. 확신의 '정화'는 정의 협소화 +
forward 프롬프트가 담당하고, 백필은 geo_scope 백필과 같은 순수 additive.

기본 = dry-run: effect_strength IS NULL인 CAUSES/BENEFITS_FROM 엣지의 (from, to, mechanism)을
sonnet 배치로 범주 판정 → 계획을 사람이 검토 가능한 목록으로 출력·저장. --apply는 저장된 계획만
UPDATE (LLM 재호출 없음). 애매하면 strength='unknown'·direction=null — 억지 지정 금지(거짓 정밀 §3).

사용법:
  python scripts/backfill_effect_strength.py                # dry-run (계획 생성·저장)
  python scripts/backfill_effect_strength.py --apply        # 저장된 계획 적용
  python scripts/backfill_effect_strength.py --limit 200
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db
from pipeline.enrich import _call_claude_code, _parse_json, llm_engine
from pipeline.narrative import EFFECT_DIRECTIONS, EFFECT_STRENGTHS

DEFAULT_PLAN = Path(__file__).resolve().parent.parent / "logs" / "effect_backfill_plan.json"
BATCH = 15            # 콜당 엣지 수
MODEL = "sonnet"      # 효과 크기·방향은 mechanism 해석이 필요 — haiku보다 상위 티어


def _candidates(conn, limit: int) -> list[dict]:
    """effect_strength 미상 인과 엣지 — (from, to, mechanism, rel)만 판정에 쓴다."""
    return [dict(r) for r in conn.execute("""
        SELECT er.id, s.name AS frm, d.name AS too, er.mechanism, er.rel_type
        FROM entity_relations er
        JOIN entities s ON s.id = er.src_id
        JOIN entities d ON d.id = er.dst_id
        WHERE er.effect_strength IS NULL AND er.rel_type IN ('CAUSES','BENEFITS_FROM')
        ORDER BY er.id LIMIT ?""", (limit,)).fetchall()]


def _build_batch_prompt(batch: list[dict]) -> str:
    lines = "\n".join(
        f"{i}. [{e['rel_type']}] {e['frm']} → {e['too']}"
        + (f" ({e['mechanism']})" if e.get("mechanism") else "")
        for i, e in enumerate(batch))
    return (
        "너는 투자 인과 주장의 '효과 크기'와 '효과 방향'을 판정한다. 이는 '주장이 맞다는 확신'과 "
        "**별개 축**이다 — 관계가 성립한다고 가정할 때 결과에 미치는 영향의 크기·방향만 본다.\n"
        "effect_strength(성립 시 효과 크기): unknown|weak|moderate|strong. "
        "숫자 금지. 판단 근거가 약하면 'unknown', 버킷 경계가 애매하면 낮은 쪽(과대평가 금지).\n"
        "  - strong: 큰 영향 — 이 원인이 결과의 주요 동인.\n"
        "  - moderate: 뚜렷하나 부차적. weak: 있으나 미미.\n"
        "effect_direction(원인이 결과를 늘리나/줄이나): positive|negative|mixed. "
        "판단 어려우면 null.\n"
        "  - BENEFITS_FROM은 from(수혜자)이 to(동인)에서 이득을 보는 관계 — 대개 positive.\n"
        'JSON만 출력: {"assignments": [{"i": 정수 인덱스, "strength": "범주", "direction": "범주 또는 null"}]}\n'
        f"[인과 고리 {len(batch)}개]\n{lines}"
    )


def _judge_batch(batch: list[dict], model: str = MODEL) -> dict[int, dict]:
    """배치 → {entity_relation_id: {strength, direction}}. 어휘 밖·미판정은 제외."""
    raw = _call_claude_code(_build_batch_prompt(batch), model=model, timeout=300)
    data = _parse_json(raw)
    out: dict[int, dict] = {}
    for a in (data.get("assignments") or []):
        try:
            idx = int(a.get("i"))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(batch)):
            continue
        strength = a.get("strength") if a.get("strength") in EFFECT_STRENGTHS else None
        if not strength:
            continue  # strength 없으면 스킵(null 유지 — 억지 지정 금지)
        direction = a.get("direction") if a.get("direction") in EFFECT_DIRECTIONS else None
        out[batch[idx]["id"]] = {"strength": strength, "direction": direction}
    return out


def run_dry(limit: int, plan_path: Path, model: str = MODEL) -> None:
    conn = get_connection()
    candidates = _candidates(conn, limit)
    print(f"[후보] effect_strength IS NULL 인과 엣지 {len(candidates)}개 (limit={limit}, model={model})")
    if not candidates:
        conn.close()
        return
    if llm_engine() != "claude-code":
        print("판정 불가 — .env ENRICH_ENGINE=claude-code 필요. 후보만 세고 종료.")
        conn.close()
        return

    by_id = {e["id"]: e for e in candidates}
    assigned: dict[int, dict] = {}
    for i in range(0, len(candidates), BATCH):
        batch = candidates[i:i + BATCH]
        try:
            assigned.update(_judge_batch(batch, model))
        except Exception as ex:  # noqa: BLE001 — 배치 하나 실패가 전체를 막지 않게
            print(f"  배치 {i // BATCH} 판정 실패: {str(ex)[:120]}")

    dist: dict[str, int] = {}
    for v in assigned.values():
        dist[v["strength"]] = dist.get(v["strength"], 0) + 1
    null_n = len(candidates) - len(assigned)

    print(f"\n[판정] 지정 {len(assigned)}개 / unknown 유지 {null_n}개")
    print("[강도 분포] " + " · ".join(f"{k} {v}" for k, v in sorted(dist.items(), key=lambda x: -x[1]))
          + f" · 미판정 {null_n}")
    print("\n=== 대표 예시 (최대 6개) ===")
    for rid, v in list(assigned.items())[:6]:
        e = by_id[rid]
        print(f"  [{v['strength']}/{v['direction'] or '방향미상'}] {e['frm']} → {e['too']}"
              + (f"  ({e['mechanism'][:55]})" if e.get("mechanism") else ""))

    plan = {"limit": limit,
            "plan": [{"id": rid, "strength": v["strength"], "direction": v["direction"],
                      "frm": by_id[rid]["frm"], "too": by_id[rid]["too"]}
                     for rid, v in assigned.items()]}
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[계획 저장] {plan_path}  (검토 후 --apply 로 {len(assigned)}개 적용)")
    conn.close()


def run_apply(plan_path: Path) -> None:
    if not plan_path.exists():
        print(f"계획 파일 없음: {plan_path} — 먼저 dry-run 실행")
        sys.exit(1)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    items = plan.get("plan") or []
    if not items:
        print("계획에 적용할 판정이 없음.")
        return
    conn = get_connection()
    applied = 0
    for it in items:
        strength = it.get("strength")
        if strength not in EFFECT_STRENGTHS:
            continue
        direction = it.get("direction") if it.get("direction") in EFFECT_DIRECTIONS else None
        cur = conn.execute(
            "UPDATE entity_relations SET effect_strength=?, effect_direction=? "
            "WHERE id=? AND effect_strength IS NULL",
            (strength, direction, it["id"]))
        applied += cur.rowcount
    conn.commit()
    conn.close()
    print(f"[적용 완료] {applied}개 엣지에 effect_strength/direction 기록")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="저장된 계획 적용 (기본=dry-run)")
    ap.add_argument("--limit", type=int, default=3000, help="판정 후보 상한")
    ap.add_argument("--model", type=str, default=MODEL, help="판정 모델 (sonnet|opus|haiku)")
    ap.add_argument("--plan", type=str, default=str(DEFAULT_PLAN))
    args = ap.parse_args()

    init_db()
    plan_path = Path(args.plan)
    if args.apply:
        run_apply(plan_path)
    else:
        run_dry(args.limit, plan_path, args.model)


if __name__ == "__main__":
    main()
