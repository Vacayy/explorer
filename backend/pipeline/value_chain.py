"""밸류체인 지도 — 최종 수요 → 대만 공급 단계 → 한국 종목 (docs/specs/value-chain.md, LLM 0).

노드는 '공급 단계'(회사 묶음)다. 대만 노드는 소속 회사들의 월매출 합으로 관측하고, 한국 종목은 자기 단계 노드에 붙는다.
엣지는 공급 방향(from이 to에 판다·설비를 댄다)으로 한 번만 저장한다(온톨로지 원칙 2: 단방향, 역방향은 질의로).
- kind=supply: 부품·제품이 from → to로 흐른다
- kind=capex:  to의 증설·투자가 from의 매출이 된다(장비·시공)
방향은 사업 구조로 정한다(D-250). 데이터(pipeline/value_chain_lags)는 그 방향 위에서 시차·강도만 잰다.

개별 기업 노드·사실 엣지가 아니라 묶음이라 온톨로지(entity_relations)에는 넣지 않는다(D-251).
"""
from __future__ import annotations

# 최종 수요. AI·스마트폰은 미국 수요 기업 분기 실적(pipeline/us_fundamentals)으로 관측한다(US_OBS). PC는 대만 PC 브랜드가 대리 관측
DEMANDS = [
    ("ai", "AI 데이터센터 수요", "하이퍼스케일러·AI 랩 설비 투자"),
    ("pc", "PC·노트북 수요", "소비자·기업 PC 교체"),
    ("mobile", "스마트폰·소비 전자 수요", "스마트폰·웨어러블·가전"),
]

# (키, 이름, 대만 회사 코드, 한국 종목 코드, 한 줄 설명)
NODES = [
    # 조립·브랜드(수요에 가장 가까운 대만 단계)
    ("ai_odm", "AI 서버 ODM", ["2382", "3231", "6669", "2317"], [], "GPU 서버 랙 조립"),
    ("pc_brand", "PC 브랜드", ["2357", "2353", "2377"], [], "노트북·데스크톱·게이밍"),
    ("nb_odm", "노트북 ODM", ["2324"], [], "노트북 위탁 생산"),
    ("mobile_asm", "스마트폰 조립·부품", ["4938", "3008"], [], "아이폰 조립·카메라 렌즈"),
    ("ai_accel", "AI 가속기", [], [], "엔비디아·AMD GPU·가속기(미국 분기 매출로 관측)"),
    ("dc_network", "데이터센터 네트워크", ["2345", "3380"], [], "스위치·네트워크 장비"),
    # 부품
    ("server_parts", "서버 전원·냉각·기구", ["2308", "2301", "3017", "3324", "3653", "2421", "8210", "2059", "3665", "3533"], [], "전원·수랭·섀시·레일·케이블·소켓"),
    ("optical", "광통신 부품", ["3081", "4979", "3163", "6442", "3363"], ["046970"], "광소자·에피·광커넥터"),
    ("pcb", "서버·스위치 PCB", ["2368", "3044", "4958"], [], "고다층 PCB"),
    ("ccl", "CCL(동박적층판)", ["2383", "6274", "6213"], [], "고속 CCL"),
    ("abf", "패키지 기판(ABF)", ["3037", "8046", "3189"], ["009150"], "FC-BGA 기판"),
    ("mlcc", "MLCC·수동부품", ["2327"], ["009150"], "적층 세라믹 콘덴서"),
    ("memory", "메모리", ["2408", "2344", "2337"], ["005930", "000660"], "DRAM·NAND·NOR"),
    ("mem_module", "메모리 모듈", ["3260", "2451"], [], "소비자 메모리 모듈·SSD"),
    ("display", "디스플레이 패널", ["2409", "3481"], [], "노트북·모니터 패널"),
    # 칩
    ("ic_design", "IC 설계", ["2454", "3034", "2379", "3661", "3443", "5274", "4966", "4919", "8299"], [], "팹리스·ASIC 설계 서비스"),
    ("foundry", "파운드리", ["2330", "2303", "5347", "6770"], ["005930"], "웨이퍼 위탁 생산"),
    ("osat", "후공정(OSAT)", ["3711", "6239", "8150"], ["067310", "036540"], "패키징·메모리 후공정"),
    ("test", "테스트·소켓·프로브", ["2449", "6257", "6515", "6510", "6223"], ["095340"], "테스트 하우스·소켓·프로브카드"),
    # 소재·장비
    ("wafer", "실리콘 웨이퍼", ["6488", "3532"], [], "실리콘 웨이퍼"),
    ("fab_equip", "팹·패키징 장비·시공", ["3131", "3583", "6196", "2404", "3680", "2360"], [], "습식 장비·클린룸·마스크 포드·계측"),
    # 한국 고유 단계(대만 동종 없음 — 관측은 한국 쪽 원천으로)
    ("kr_pkg_equip", "첨단 패키징 장비(한국)", [], ["031980", "042700"], "리플로우·TC 본더"),
    ("kr_smt_insp", "SMT 검사장비(한국)", [], ["098460"], "SPI·AOI"),
    ("kr_sub_equip", "기판 습식 장비(한국)", [], ["323280"], "PCB·기판 습식 공정"),
    ("kr_stf", "프로브카드용 세라믹 기판(한국)", [], ["252990"], "STF"),
]

# (from, to, kind, 이유) — from이 to에 판다(supply) / to의 투자가 from의 매출(capex). to가 DEMANDS 키면 최종 수요
EDGES = [
    ("ai_odm", "ai", "supply", "GPU 서버 랙을 하이퍼스케일러에 납품"),
    ("dc_network", "ai", "supply", "데이터센터 스위치"),
    ("pc_brand", "pc", "supply", "PC 판매"),
    ("nb_odm", "pc_brand", "supply", "브랜드의 노트북을 위탁 생산"),
    ("server_parts", "ai_odm", "supply", "서버 전원·냉각·기구"),
    ("optical", "dc_network", "supply", "광트랜시버·광부품"),
    ("pcb", "ai_odm", "supply", "서버 메인보드·가속기 보드"),
    ("pcb", "dc_network", "supply", "스위치 보드"),
    ("ccl", "pcb", "supply", "PCB 원판"),
    ("abf", "osat", "supply", "패키지 기판"),
    ("mlcc", "ai_odm", "supply", "서버 보드 MLCC"),
    ("mlcc", "nb_odm", "supply", "노트북 보드 MLCC"),
    ("memory", "ai_odm", "supply", "서버 DRAM"),
    ("ai_accel", "ai_odm", "supply", "GPU 보드·가속기를 서버 ODM에"),
    ("memory", "ai_accel", "supply", "HBM"),
    ("foundry", "ai_accel", "supply", "GPU 웨이퍼·CoWoS 패키징"),
    ("osat", "ai_accel", "supply", "후공정·테스트"),
    ("mobile_asm", "mobile", "supply", "아이폰 조립·카메라 렌즈"),
    ("memory", "mobile_asm", "supply", "모바일 DRAM·NAND"),
    ("mlcc", "mobile_asm", "supply", "스마트폰 MLCC"),
    ("memory", "mem_module", "supply", "모듈용 메모리 칩"),
    ("memory", "nb_odm", "supply", "노트북 DRAM·SSD"),
    ("mem_module", "pc", "supply", "소비자 모듈·SSD"),
    ("display", "nb_odm", "supply", "노트북 패널"),
    ("ic_design", "ai_odm", "supply", "ASIC·BMC·인터페이스 칩"),
    ("ic_design", "nb_odm", "supply", "PC·주변기기 칩"),
    ("ic_design", "mobile", "supply", "모바일 AP·구동 IC"),
    ("foundry", "ic_design", "supply", "설계사의 칩을 생산"),
    ("osat", "ic_design", "supply", "패키징·테스트 위탁"),
    ("test", "ic_design", "supply", "테스트 소켓·프로브·테스트 위탁"),
    ("wafer", "foundry", "supply", "웨이퍼"),
    ("wafer", "memory", "supply", "웨이퍼"),
    ("fab_equip", "foundry", "capex", "팹 증설"),
    ("fab_equip", "osat", "capex", "첨단 패키징 증설"),
    ("kr_pkg_equip", "foundry", "capex", "CoWoS 증설(리플로우·TC 본더)"),
    ("kr_pkg_equip", "osat", "capex", "OSAT 패키징 증설"),
    ("kr_pkg_equip", "memory", "capex", "HBM 증설"),
    ("kr_smt_insp", "ai_odm", "capex", "서버 SMT 라인 증설"),
    ("kr_smt_insp", "nb_odm", "capex", "노트북 SMT 라인"),
    ("kr_sub_equip", "abf", "capex", "기판 증설"),
    ("kr_sub_equip", "pcb", "capex", "PCB 증설"),
    ("kr_stf", "test", "supply", "프로브카드용 세라믹 기판"),
]

# 대만 월매출 대신 미국 분기 실적으로 관측하는 칸·수요 → us_quarterly.use_key
US_OBS = {"ai": ("ai", "하이퍼스케일러 설비투자(MSFT·GOOGL·AMZN·META·ORCL)"),
          "ai_accel": ("ai_accel", "엔비디아·AMD 매출"),
          "mobile": ("mobile", "애플 매출")}

NODE_BY_KEY = {n[0]: n for n in NODES}
DEMAND_KEYS = {d[0] for d in DEMANDS}


def validate() -> list[str]:
    """지도 정합성 — 알 수 없는 노드·코드, 중복 엣지, 자기 순환"""
    from pipeline.tw_universe import CODES
    errs = []
    for key, _, tw, _, _ in NODES:
        errs += [f"{key}: 대만 코드 {c} 없음" for c in tw if c not in CODES]
    seen = set()
    for a, b, kind, _ in EDGES:
        if a not in NODE_BY_KEY:
            errs.append(f"엣지 출발 {a} 없음")
        if b not in NODE_BY_KEY and b not in DEMAND_KEYS:
            errs.append(f"엣지 도착 {b} 없음")
        if a == b or (a, b) in seen:
            errs.append(f"엣지 {a}→{b} 중복·자기 순환")
        seen.add((a, b))
    return errs


def downstream(key: str) -> list[tuple[str, str]]:
    """key가 파는 곳(바로 다음 칸)"""
    return [(b, kind) for a, b, kind, _ in EDGES if a == key]


def upstream(key: str) -> list[tuple[str, str]]:
    """key에 파는 곳(바로 앞 칸) — 단방향 저장을 질의로 역전"""
    return [(a, kind) for a, b, kind, _ in EDGES if b == key]


def us_signal(conn, key: str) -> dict:
    """분기 관측 칸(US_OBS) — 최신 분기 YoY, 직전 분기 YoY, 상태(±10%p·부호 전환), 최근 12분기"""
    from pipeline.tw_links import ACCEL_PP
    from pipeline.value_chain_lags import node_quarterly
    s = node_quarterly(conn, key)
    qs = sorted(s)
    now, prev = (s[qs[-1]] if qs else None), (s[qs[-2]] if len(qs) > 1 else None)
    state = None
    if now is not None and prev is not None:
        state = ("전환↑" if prev < 0 <= now else "전환↓" if prev >= 0 > now else
                 "가속" if now - prev >= ACCEL_PP else "둔화" if now - prev <= -ACCEL_PP else "유지")
    r = lambda v: round(v, 1) if v is not None else None  # noqa: E731
    return {"yoy_3m": r(now), "yoy_3m_prev": r(prev), "state": state, "period": qs[-1] if qs else None,
            "series": [{"ym": q, "yoy": round(s[q], 1)} for q in qs[-12:]]}


def read_map() -> dict:
    """화면용 지도 — 노드(대만 회사·한국 종목·이번 달 3개월 YoY와 상태), 엣지(측정 시차·판정), 위약 기준.
    분기 관측 칸·수요(US_OBS)는 미국 분기 실적의 YoY와 상태(freq='Q')."""
    from database import get_connection
    from pipeline.tw_links import tw_signal
    from pipeline.tw_universe import COMPANIES
    from pipeline.value_chain_lags import measure_all
    names = {c: n for c, n, *_ in COMPANIES}
    conn = get_connection()
    try:
        kr_names = {r["stock_code"]: r["corp_name"] for r in conn.execute(
            "SELECT stock_code, corp_name FROM companies WHERE stock_code IN (%s)" % ",".join("?" * len({k for n in NODES for k in n[3]})),
            sorted({k for n in NODES for k in n[3]}))}
        as_of = conn.execute("SELECT MAX(ym) FROM tw_monthly_revenue").fetchone()[0]
        demands = []
        for k, n, d in DEMANDS:
            sig = us_signal(conn, k) if k in US_OBS else {}
            demands.append({"key": k, "name": n, "description": d, "obs_label": US_OBS[k][1] if k in US_OBS else None,
                            "yoy_3m": sig.get("yoy_3m"), "yoy_3m_prev": sig.get("yoy_3m_prev"), "state": sig.get("state"),
                            "period": sig.get("period"), "series": sig.get("series", [])})
        nodes = []
        for key, name, tw, kr, desc in NODES:
            us = key in US_OBS
            sig = us_signal(conn, key) if us else (tw_signal(conn, tw) if tw else {})
            nodes.append({"key": key, "name": name, "description": desc, "freq": "Q" if us else "M",
                          "obs_label": US_OBS[key][1] if us else None, "period": sig.get("period") if us else sig.get("ym"),
                          "tw": [{"code": c, "name": names.get(c, c)} for c in tw],
                          "kr": [{"code": c, "name": kr_names.get(c, c)} for c in kr],
                          "yoy_3m": sig.get("yoy_3m"), "yoy_3m_prev": sig.get("yoy_3m_prev"), "state": sig.get("state"),
                          "series": sig.get("series", [])})
    finally:
        conn.close()
    measured = measure_all()
    return {"as_of": as_of, "demands": demands,
            "tiers": [{"key": k, "label": v} for k, v in TIERS], "lanes": [{"key": k, "label": v} for k, v in LANES],
            "layout": {k: {"tier": t, "lane": l} for k, (t, l) in LAYOUT.items()},
            "nodes": nodes, "edges": measured["edges"], "thresholds": measured["thresholds"]}


def propagation(vmap: dict | None = None, confirms: list[dict] | None = None) -> dict:
    """번지는 중 — 한국 확인 전·엇갈림·선행 경보 (docs/specs/value-chain.md §5).

    - 한국 확인 전: 대만이 오르는데(↑) 한국 수출·공시 어느 쪽도 오르지 않은 종목 — 공시 시차의 빈칸
    - 엇갈림: 관측한 원천끼리 방향이 반대(↑와 ↓가 함께)
    - 선행 경보: 판정이 확인·부분이고 시차가 일관된 엣지 중 |시차|≥2개월, 앞선 칸이 방향을 바꿨다(가속·둔화·전환).
      뒤따를 칸이 이미 같은 방향이면 '반영됨', 아니면 '대기'
    """
    from pipeline.kr_confirm import confirm
    from pipeline.tw_links import LINKS
    vmap = vmap or read_map()
    if confirms is None:
        confirms = [confirm(c) for c in sorted({link[0] for link in LINKS})]
    names = {k["code"]: k["name"] for n in vmap["nodes"] for k in n["kr"]}
    waiting, diverging = [], []
    for c in confirms:
        d = c["directions"]
        observed = {k: v for k, v in d.items() if v}
        row = {"stock_code": c["stock_code"], "name": names.get(c["stock_code"], c["stock_code"]), "directions": d,
               "agree_up": c["agree_up"], "observed": c["observed"]}
        if "up" in observed.values() and "down" in observed.values():
            diverging.append(row)
        elif d.get("taiwan") == "up" and d.get("trade") != "up" and d.get("disclosure") != "up":
            waiting.append(row)
    state_dir = {"가속": "up", "전환↑": "up", "둔화": "down", "전환↓": "down"}
    nodes = {n["key"]: n for n in vmap["nodes"]}
    leads = []
    for e in vmap["edges"]:
        lag = e.get("lag")
        if e["verdict"] not in ("확인", "부분") or not e.get("lag_consistent") or lag is None or abs(lag) < 2:
            continue
        leader, follower = (e["from"], e["to"]) if lag > 0 else (e["to"], e["from"])
        ls = nodes.get(leader, {}).get("state")
        if ls not in state_dir:
            continue
        fs = nodes.get(follower, {}).get("state")
        leads.append({"leader": leader, "leader_name": nodes[leader]["name"], "leader_state": ls,
                      "follower": follower, "follower_name": nodes[follower]["name"], "follower_state": fs,
                      "months": abs(lag), "verdict": e["verdict"],
                      "status": "반영됨" if state_dir.get(fs) == state_dir[ls] else "대기",
                      "kr": nodes[follower]["kr"]})
    return {"as_of": vmap["as_of"], "waiting": waiting, "diverging": diverging, "leads": leads}


# ── 스윔레인 배치 (2026-10-18) — 열 = 밸류체인 단계(돈의 흐름: 수요 → 상류), 행 = 수요처 레인 ──
TIERS = [
    ("demand", "최종 수요"), ("system", "완제품·조립"), ("module", "부품·모듈"),
    ("chip", "칩(설계·메모리)"), ("fab", "칩 생산·후공정"), ("material", "소재·장비"),
]
LANES = [
    ("ai", "AI 데이터센터"), ("pc", "PC·노트북"), ("mobile", "스마트폰"),
    ("common", "공통 — 여러 수요에 함께 공급"),
]
# 칸 → (단계, 레인). 여러 수요에 공급하는 칸은 공통 레인
LAYOUT = {
    "ai": ("demand", "ai"), "pc": ("demand", "pc"), "mobile": ("demand", "mobile"),
    "ai_odm": ("system", "ai"), "dc_network": ("system", "ai"),
    "pc_brand": ("system", "pc"), "nb_odm": ("system", "pc"),
    "mobile_asm": ("system", "mobile"),
    "ai_accel": ("module", "ai"), "server_parts": ("module", "ai"), "optical": ("module", "ai"), "pcb": ("module", "ai"),
    "mem_module": ("module", "pc"), "display": ("module", "pc"),
    "mlcc": ("module", "common"), "kr_smt_insp": ("material", "common"),
    "ic_design": ("chip", "common"), "memory": ("chip", "common"),
    "foundry": ("fab", "common"), "osat": ("fab", "common"), "test": ("fab", "common"),
    "ccl": ("material", "ai"), "abf": ("material", "common"), "wafer": ("material", "common"),
    "fab_equip": ("material", "common"), "kr_pkg_equip": ("material", "common"),
    "kr_sub_equip": ("material", "common"), "kr_stf": ("material", "common"),
}


def validate_layout() -> list[str]:
    tiers, lanes = {t for t, _ in TIERS}, {l for l, _ in LANES}
    keys = set(NODE_BY_KEY) | DEMAND_KEYS
    errs = [f"배치 없음: {k}" for k in sorted(keys - set(LAYOUT))]
    errs += [f"알 수 없는 배치 {k}: {v}" for k, v in LAYOUT.items() if v[0] not in tiers or v[1] not in lanes or k not in keys]
    return errs
