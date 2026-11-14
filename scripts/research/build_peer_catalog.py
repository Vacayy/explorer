"""Build the public business-evidence bundle from reviewed research artifacts.

Usage: python scripts/research/build_peer_catalog.py --research-dir logs/peer-research/2026-11-01
No DB/network access; never copies personal priorities, mentions, holdings or prices.
"""
import argparse
import json
from pathlib import Path

EXTRA_GROUPS = {
    'bank_financial_holding': ('은행 금융지주', 'product', '지주회사 단위 비교. 은행·보험·증권 이익 구성 차이로 은행 순수사업 직접 Peer는 아님.'),
    'securities_brokerage': ('증권업 관찰군', 'product', '투자중개·자산관리·시장거래 공통분모. 해외·IB·자기자본 투자와 규모 차이를 보존.'),
    'plant_epc': ('플랜트 EPC 부분 Peer', 'product', '플랜트 사업의 부분 중첩. 현대건설·대우건설은 토목·건축·주택을 겸하며 기업 전체의 순수 플랜트 비교가 아님.'),
    'battery_value_chain': ('배터리 밸류체인', 'value_chain', '배터리 셀과 양극재는 제조 단계가 다른 공급망. 전체 기업의 직접 경쟁 관계가 아님.'),
    'battery_cell': ('배터리 셀', 'product', '전기차·ESS용 셀 사업 중첩. 폼팩터·화학계·고객과 전자재료 등 다른 사업 노출 차이 보존.'),
    'battery_cathode': ('배터리 양극재', 'product', '양극재 제품 중첩. 화학계·고객·전구체 내재화와 음극재 등 사업 구성 차이 확인 필요.'),
    'beauty_value_chain': ('화장품·뷰티 밸류체인', 'value_chain', '브랜드·뷰티기기·ODM 제조를 포함한 넓은 수요 관찰군. 직접 경쟁과 공급망 관계 구분.'),
    'cosmetics_odm': ('화장품 ODM 제조', 'product', '화장품 연구개발·위탁제조 사업 중첩. 제품군·고객·국가와 연결 자회사의 의약품 노출 차이 보존.'),
    'beauty_brand_device': ('뷰티 브랜드·기기', 'product', '브랜드 판매와 뷰티 디바이스 사업. ODM 제조와 구분하며 단일기업 그룹은 Peer 기준선 미제공.'),
    'power_infrastructure': ('전력 인프라', 'value_chain', '전력 생산·송배전 관련 제품의 넓은 관찰군. 변압기·개폐장치·전선은 별도 제품군으로 비교.'),
    'power_transformer': ('전력 변압기', 'product', '변압기 제품 존재 기준. 정격전압·고객·지역·연결범위가 달라 회사 전체의 직접 경쟁을 뜻하지 않음.'),
    'switchgear': ('차단기·개폐장치', 'product', '차단기·개폐장치 제품 중첩. 제품 전압과 적용 시장 차이 및 다른 사업 노출을 함께 확인.'),
    'power_cable': ('전력 케이블', 'product', '전력 케이블 사업 중첩. 해저·초고압·배전 등 세부 제품과 지주회사 구조 차이를 보존.'),
    'shipbuilding': ('조선', 'value_chain', '상선·해양·특수선의 넓은 관찰군. 선종·군함 비중·엔진사업과 합병 이후 범위가 달라 직접 경쟁은 제품별로 확인.'),
    'defense_value_chain': ('방산 밸류체인', 'value_chain', '지상·항공·유도무기·함정은 서로 다른 시장. 연결 자회사 중복 노출을 포함하므로 독립기업 동일가중 신호에 바로 사용하지 않음.'),
    'defense_aerospace': ('방산 항공·우주', 'product', '항공기 체계·엔진·우주 사업은 밸류체인 역할이 다름. 제품 존재를 관찰하며 직접 대체 관계로 단정하지 않음.'),
    'defense_ground': ('지상 방산', 'product', '지상 무기체계의 사업 존재 근거. 단일기업이면 그룹 상대강도 기준선으로 사용할 수 없음.'),
    'defense_guided_weapons': ('유도무기', 'product', '유도무기 사업 존재 근거. 제품 체계·고객·독립기업 수 추가 검증 필요.'),
}

def extend_catalog(catalog, extension):
    """Merge reviewed business evidence; preserve existing memberships and sources."""
    groups = {g['id']: g for g in catalog['groups']}
    for group in extension['groups']:
        groups[group['id']] = group
    companies = {c['code']: c for c in catalog['companies']}
    for addition in extension['companies']:
        prior = companies.get(addition['code'])
        if prior:
            merged = {**prior, **addition}
            for field in ('aliases', 'products', 'groupIds', 'caveats', 'sources'):
                merged[field] = list(prior[field])
                for value in addition[field]:
                    if value not in merged[field]:
                        merged[field].append(value)
            companies[addition['code']] = merged
        else:
            companies[addition['code']] = addition
    assert all(set(c['groupIds']) <= groups.keys() for c in companies.values()), 'unknown group'
    return dict(version=extension['version'], asOf=extension['asOf'],
                groups=list(groups.values()), companies=sorted(companies.values(), key=lambda c: c['name']))


def build(root: Path):
    source_companies = json.loads((root / 'phase2/companies41.json').read_text())
    source_groups = json.loads((root / 'phase2/group_definitions.json').read_text())
    groups = [dict(id=g['id'], name=g['name'], scope='value_chain' if g['id']=='diversified_materials' else 'product', interpretation=g['interpretation']) for g in source_groups]
    groups.insert(0, dict(id='semiconductor_value_chain', name='반도체 밸류체인', scope='value_chain', interpretation='제조·설계·소재·부품·장비·서비스를 포함한 넓은 관찰군. 직접 경쟁 관계와 구분.'))
    companies = []
    for c in source_companies:
        ids = ['semiconductor_value_chain'] + [g['id'] for g in source_groups if c['code'] in g['members']]
        companies.append(normalize(c, ids))
    extras = []
    for filename in ['power.json', 'ship_defense.json']:
        extras.extend(json.loads((root / 'phase4' / filename).read_text()))
    extras.extend(json.loads((root / 'phase5/coverage.json').read_text()))
    extras.extend(json.loads((root / 'phase6/coverage.json').read_text()))
    extra_ids = {g for c in extras for g in c['groups']}
    for gid, (name, scope, interpretation) in EXTRA_GROUPS.items():
        if gid in extra_ids:
            groups.append(dict(id=gid, name=name, scope=scope, interpretation=interpretation))
    companies.extend(normalize(c, c['groups']) for c in extras)
    assert len({c['code'] for c in companies}) == len(companies), 'duplicate company'
    known = {g['id'] for g in groups}
    assert all(set(c['groupIds']) <= known for c in companies), 'unknown group'
    return dict(version='2026-11-01.3', asOf='2026-11-01', groups=groups, companies=sorted(companies, key=lambda c:c['name']))

def normalize(c, ids):
    sources = []
    for s in c['sources']:
        source = dict(url=s['url'], claim=s['claim'], verification=s.get('verification', s.get('access_status', 'research_record')))
        if s.get('period'): source['period'] = s['period']
        if s.get('publication_date'): source['publishedAt'] = s['publication_date']
        sources.append(source)
    return dict(code=c['code'], name=c['name'], asOf=c.get('as_of','2026-11-01'), products=[c['products']] if isinstance(c['products'], str) else c['products'], aliases=c.get('aliases', []), groupIds=ids, caveats=c['caveats'], sources=sources)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research-dir', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path('frontend/src/data/peer-catalog.json'))
    parser.add_argument('--extension', type=Path, help='Reviewed public evidence additions and group definitions')
    args = parser.parse_args()
    catalog = build(args.research_dir)
    if args.extension:
        catalog = extend_catalog(catalog, json.loads(args.extension.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2)+'\n')
    print(f"{len(catalog['companies'])} companies / {len(catalog['groups'])} groups -> {args.output}")
