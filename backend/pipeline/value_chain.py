"""밸류체인 지도 — 최종 수요 → 대만 공급 단계 → 한국 종목 (docs/specs/value-chain.md, LLM 0).

노드는 '공급 단계'(회사 묶음)다. 대만 노드는 소속 회사들의 월매출 합으로 관측하고, 한국 종목은 자기 단계 노드에 붙는다.
엣지는 공급 방향(from이 to에 판다·설비를 댄다)으로 한 번만 저장한다(온톨로지 원칙 2: 단방향, 역방향은 질의로).
- kind=supply: 부품·제품이 from → to로 흐른다
- kind=capex:  to의 증설·투자가 from의 매출이 된다(장비·시공)
방향은 사업 구조로 정한다(D-250). 데이터(pipeline/value_chain_lags)는 그 방향 위에서 시차·강도만 잰다.

개별 기업 노드·사실 엣지가 아니라 묶음이라 온톨로지(entity_relations)에는 넣지 않는다(D-251).
"""
from __future__ import annotations

# 최종 수요 — 대만 데이터로 직접 관측하지 않는다(가장 아래쪽 대만 노드가 대리 관측)
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
    ("nb_odm", "노트북 ODM", ["2324", "4938"], [], "노트북 위탁 생산"),
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
    ("memory", "ai_odm", "supply", "서버 DRAM·HBM(가속기 경유)"),
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


def read_map() -> dict:
    """화면용 지도 — 노드(대만 회사·한국 종목·이번 달 3개월 YoY와 상태), 엣지(측정 시차·판정), 위약 기준"""
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
        nodes = []
        for key, name, tw, kr, desc in NODES:
            sig = tw_signal(conn, tw) if tw else {}
            nodes.append({"key": key, "name": name, "description": desc,
                          "tw": [{"code": c, "name": names.get(c, c)} for c in tw],
                          "kr": [{"code": c, "name": kr_names.get(c, c)} for c in kr],
                          "yoy_3m": sig.get("yoy_3m"), "yoy_3m_prev": sig.get("yoy_3m_prev"), "state": sig.get("state"),
                          "series": sig.get("series", [])})
    finally:
        conn.close()
    measured = measure_all()
    return {"as_of": as_of, "demands": [{"key": k, "name": n, "description": d} for k, n, d in DEMANDS],
            "nodes": nodes, "edges": measured["edges"], "thresholds": measured["thresholds"]}
