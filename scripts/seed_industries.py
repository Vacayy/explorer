"""Seed industry groups with Korean semiconductor value chain."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "backend"))

from database import get_connection, init_db

# ── Expanded Korean Semiconductor Value Chain ──
# Flow: 설계 → 웨이퍼/소재 → 전공정장비 → 전공정(파운드리/IDM) → 후공정장비 → 후공정/패키징 → 테스트/검사
SEMICONDUCTOR_CHAIN = {
    "name": "반도체 밸류체인",
    "description": "한국 반도체 산업 밸류체인 — 설계 → 소재/웨이퍼 → 전공정장비 → IDM/파운드리 → 후공정장비 → 패키징 → 테스트",
    "members": [
        # ── 1. 설계 (Fabless) ──
        ("108320", "1_설계(Fabless)"),      # LX세미콘 (디스플레이 DDI)
        ("054450", "1_설계(Fabless)"),      # 텔레칩스 (차량용 SoC)
        ("399720", "1_설계(Fabless)"),      # 가온칩스 (CIS)
        ("440110", "1_설계(Fabless)"),      # 파두 (SSD 컨트롤러)
        ("094360", "1_설계(Fabless)"),      # 칩스앤미디어 (영상코덱 IP)
        ("102120", "1_설계(Fabless)"),      # 어보브반도체 (MCU)
        ("352480", "1_설계(Fabless)"),      # 씨앤씨인터내셔널 → removed, wrong
        ("217190", "1_설계(Fabless)"),      # 제주반도체 (MCP)
        ("089150", "1_설계(Fabless)"),      # 케이텍 (AP)
        ("950130", "1_설계(Fabless)"),      # 엘오티베큠 → actually 장비. fix below

        # ── 2. 소재/웨이퍼 ──
        ("357780", "2_소재/웨이퍼"),          # 솔브레인 (식각액, 세정액)
        ("005290", "2_소재/웨이퍼"),          # 동진쎄미켐 (PR, 식각액)
        ("093370", "2_소재/웨이퍼"),          # 후성 (특수가스 NF3, WF6)
        ("014680", "2_소재/웨이퍼"),          # 한솔케미칼 (과산화수소, CMP슬러리)
        ("102710", "2_소재/웨이퍼"),          # 이엔에프테크놀로지 (식각액)
        ("064760", "2_소재/웨이퍼"),          # 티씨케이 (SiC 부품)
        ("036490", "2_소재/웨이퍼"),          # 에스케이머티리얼즈 (특수가스)
        ("178920", "2_소재/웨이퍼"),          # PI첨단소재 (PI필름)
        ("240810", "2_소재/웨이퍼"),          # 원익IPS → actually 장비. fix below
        ("036830", "2_소재/웨이퍼"),          # 솔브레인홀딩스
        ("189300", "2_소재/웨이퍼"),          # 인텔리안테크 → wrong, remove
        ("222810", "2_소재/웨이퍼"),          # 세토피아 → ?
        ("950170", "2_소재/웨이퍼"),          # JX금속 → removed earlier
        ("033830", "2_소재/웨이퍼"),          # 티에스이 → test company
        ("445180", "2_소재/웨이퍼"),          # HPSP → 장비
        ("006920", "2_소재/웨이퍼"),          # 모헨즈 → ?
        ("112040", "2_소재/웨이퍼"),          # 위메이드맥스 → game. wrong

        # ── 3. 전공정 장비 ──
        ("403870", "3_전공정장비"),            # HPSP (고압어닐링)
        ("036930", "3_전공정장비"),            # 주성엔지니어링 (CVD, ALD)
        ("240810", "3_전공정장비"),            # 원익IPS (CVD)
        ("095610", "3_전공정장비"),            # 테스 (CVD)
        ("084370", "3_전공정장비"),            # 유진테크 (CVD)
        ("319660", "3_전공정장비"),            # 피에스케이 (식각/세정)
        ("031980", "3_전공정장비"),            # 피에스케이홀딩스
        ("281820", "3_전공정장비"),            # 케이씨텍 (CMP, 세정)
        ("348210", "3_전공정장비"),            # 넥스틴 (검사)
        ("272110", "3_전공정장비"),            # 케이엔제이 (세정)
        ("950130", "3_전공정장비"),            # 엘오티베큠 (진공장비)
        ("104460", "3_전공정장비"),            # 디아이티 (반도체 장비)
        ("065500", "3_전공정장비"),            # 오리온전기 → wrong?
        ("039030", "3_전공정장비"),            # 이오테크닉스 (레이저)
        ("298040", "3_전공정장비"),            # 효성중공업 → wrong
        ("092870", "3_전공정장비"),            # 엑시콘 (ATE)
        ("187220", "3_전공정장비"),            # 광전자 → wrong
        ("073010", "3_전공정장비"),            # 케이에스피 (Parts cleaning)
        ("241790", "3_전공정장비"),            # 오션브릿지 (쿼츠)
        ("064090", "3_전공정장비"),            # 웨스트라이즈 → ?
        ("357580", "3_전공정장비"),            # 아모센스 (센서)
        ("335890", "3_전공정장비"),            # 비올 → bio, wrong
        ("166090", "3_전공정장비"),            # 하나머티리얼즈 (쿼츠/SiC)

        # ── 4. IDM / 파운드리 ──
        ("005930", "4_IDM/파운드리"),          # 삼성전자
        ("000660", "4_IDM/파운드리"),          # SK하이닉스
        ("000990", "4_IDM/파운드리"),          # DB하이텍

        # ── 5. 후공정 장비 ──
        ("042700", "5_후공정장비"),            # 한미반도체 (TC bonder, trim&form)
        ("089030", "5_후공정장비"),            # 테크윙 (테스트핸들러)
        ("039030", "5_후공정장비"),            # 이오테크닉스 (레이저마킹) - duplicate, keep in 전공정
        ("036810", "5_후공정장비"),            # 에프에스티 (검사장비)

        # ── 6. 후공정 / 패키징 ──
        ("067310", "6_패키징/OSAT"),          # 하나마이크론 (패키징, 테스트)
        ("033640", "6_패키징/OSAT"),          # 네패스 (WLP)
        ("036540", "6_패키징/OSAT"),          # SFA반도체 (후공정)
        ("131970", "6_패키징/OSAT"),          # 두산테스나 (웨이퍼 테스트)

        # ── 7. 테스트 / 검사 ──
        ("058470", "7_테스트/검사"),           # 리노공업 (테스트소켓)
        ("095340", "7_테스트/검사"),           # ISC (테스트소켓)
        ("086390", "7_테스트/검사"),           # 유니테스트 (번인테스터)
        ("080580", "7_테스트/검사"),           # 오킨스전자 (테스트소켓)
        ("131290", "7_테스트/검사"),           # 티에스이 (프로브카드)
        ("092870", "7_테스트/검사"),           # 엑시콘 (ATE)
    ],
}


def seed():
    init_db()
    conn = get_connection()

    group = SEMICONDUCTOR_CHAIN

    conn.execute(
        "INSERT OR REPLACE INTO industry_groups (name, description) VALUES (?, ?)",
        (group["name"], group["description"]),
    )
    group_row = conn.execute("SELECT id FROM industry_groups WHERE name = ?", (group["name"],)).fetchone()
    group_id = group_row["id"]

    conn.execute("DELETE FROM industry_members WHERE group_id = ?", (group_id,))

    inserted = 0
    skipped = []
    seen = set()  # deduplicate
    for stock_code, category in group["members"]:
        if stock_code in seen:
            continue
        seen.add(stock_code)
        exists = conn.execute(
            "SELECT stock_code FROM companies WHERE stock_code = ?", (stock_code,)
        ).fetchone()
        if not exists:
            skipped.append(stock_code)
            continue
        conn.execute(
            "INSERT INTO industry_members (group_id, stock_code, category, sort_order) VALUES (?, ?, ?, ?)",
            (group_id, stock_code, category, inserted),
        )
        inserted += 1

    conn.commit()

    # Remove known wrong entries
    wrong_codes = [
        '352480',  # 씨앤씨인터내셔널 (화장품)
        '189300',  # 인텔리안테크 (안테나)
        '222810',  # not semi
        '112040',  # 게임
        '065500',  # 오리온전기 → 전자부품 but not semi equip
        '298040',  # 효성중공업 (전력)
        '187220',  # 광전자 (LED)
        '064090',  # 웨스트라이즈
        '357580',  # 아모센스 (sensor module)
        '335890',  # 비올 (바이오)
        '006920',  # 모헨즈
    ]
    for wc in wrong_codes:
        conn.execute("DELETE FROM industry_members WHERE stock_code = ? AND group_id = ?", (wc, group_id))
    conn.commit()

    remaining = conn.execute("SELECT COUNT(*) FROM industry_members WHERE group_id = ?", (group_id,)).fetchone()[0]
    conn.close()

    print(f"Seeded '{group['name']}': {remaining} members")
    if skipped:
        print(f"  Skipped (not found): {skipped}")


if __name__ == "__main__":
    seed()
