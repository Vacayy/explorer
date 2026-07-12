"""파생 신호 계산 실행 (ingest 후 후처리로 실행).

사용법: python scripts/compute_signals.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import init_db
from pipeline.signals import (compute_consensus_extreme, compute_high_52w,
                              compute_mention_surge, compute_neglect, interpret_pending)


def main():
    init_db()
    signals = compute_mention_surge()
    print(f"[mention_surge] {len(signals)}건")
    for s in sorted(signals, key=lambda x: -x["payload"]["count_7d"]):
        p = s["payload"]
        print(f"  · {s['name']}: 최근 7일 {p['count_7d']}회 (직전 7일 {p['baseline_7d']}회)"
              f"  키워드: {', '.join(p['keywords'][:3]) or '-'}")

    highs = compute_high_52w()
    print(f"[high_52w] {len(highs)}건")
    for s in sorted(highs, key=lambda x: -x["payload"]["breakout_pct"])[:10]:
        p = s["payload"]
        print(f"  · {s['name']}: 고가 {p['high']:,} (전고점 {p['prior_high_52w']:,}, +{p['breakout_pct']}%)")

    neglected = compute_neglect()
    print(f"[neglect] {len(neglected)}건 — 저평가·흑자·30일 무언급")
    for s in neglected[:8]:
        p_ = s["payload"]
        print(f"  · {s['name']} [{p_['market']}]: PER {p_['per']} · ROE {p_['roe']}% · 시총 {p_['market_cap']/1e12:.2f}조")

    extremes = compute_consensus_extreme()
    print(f"[consensus_extreme] {len(extremes)}건 — 컨센서스 극단 (진자)")
    for s in extremes[:8]:
        p_ = s["payload"]
        print(f"  · {s['name']}: {'낙관' if p_['direction']=='optimism' else '비관'} "
              f"{p_['ratio']*100:.0f}% ({p_['pos']}+/{p_['neg']}-)")

    print("[interpret]", interpret_pending())

    # K2 모순 감지 — 30분 체인 편승, 일 1회 (오늘 스캔 흔적 있으면 skip)
    from database import get_connection
    from pipeline.contradiction import ran_today, scan_contradictions
    conn = get_connection()
    todo = not ran_today(conn)
    conn.close()
    if todo:
        print("[contradiction]", scan_contradictions())


if __name__ == "__main__":
    main()
