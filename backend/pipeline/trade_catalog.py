"""Fixed shared customs catalog. No collection, personal CSV, or LLM imports."""
DEFAULT_FOLLOWS = [
    ("854232", "메모리반도체(D램·낸드·HBM)", "반도체"),
    ("854231", "시스템반도체(프로세서·컨트롤러)", "반도체"),
    ("851713", "스마트폰", "IT"),
    ("8524", "디스플레이(평판 모듈)", "IT"),
    ("850760", "전기차용 리튬이온전지", "2차전지"),
    ("8703", "승용자동차", "자동차"),
    ("8708", "자동차부품", "자동차"),
    ("2710", "석유제품", "에너지"),
    ("39", "플라스틱·합성수지", "소재"),
    ("72", "철강", "소재"),
    ("89", "선박", "기계"),
]

# Public names reflect the full HS scope, not private investment shorthand.
PUBLIC_NAMES = {'850760':'리튬이온 축전지','39':'플라스틱과 그 제품','89':'선박과 수상 구조물'}
