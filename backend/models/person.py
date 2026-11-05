"""인물 1단계 응답 모델 (ia-redesign §4.23) — 인물 홈·id 기반 상세·이름 → id 해소."""
from typing import Literal

from pydantic import BaseModel

from models.regimes import EraSource, WhoPerson

PersonRoleName = Literal["policy", "executive", "guru"]
PremiseStatus = Literal["supports", "challenges", "mixed", "untestable", "nodata"]


class PersonRole(BaseModel):
    role: PersonRoleName
    org: str | None          # 소속 표기 (연준 · NVIDIA · 오크트리 캐피털)
    org_code: str | None     # 경영자 소속 종목 — 국내 6자리 · 미국 티커
    title: str | None        # CEO · CFO · 의장 …
    source: str              # dictionary · transcript · premise · memo


class PremiseVerdict(BaseModel):
    key: str
    claim: str
    status: PremiseStatus | None


class PeopleHomeRow(BaseModel):
    entity_id: int
    name: str
    role: PersonRole | None
    doc_count: int
    mentions_7d: int
    delta_7d: int
    last_doc_title: str | None
    last_doc_id: int | None
    last_doc_at: str | None
    top_stocks: list[str]
    following: bool
    records: int             # 이 사람의 기록(1단계 = 구루 전제) 수


class RecordedPerson(BaseModel):
    entity_id: int | None    # 인물 엔티티가 없으면 null(만들지 않는다)
    name: str
    role: PersonRole | None
    doc_count: int
    premises: list[PremiseVerdict]


class PeopleHomeSummary(BaseModel):
    followed: int
    followed_mentions_7d: int
    recorded_people: int
    premises: int
    mentioned: int           # 이름이 나온 인물(묶은 이름은 한 사람)
    mentioned_2plus: int


class PeopleHome(BaseModel):
    summary: PeopleHomeSummary
    role_counts: dict[str, int]   # all · policy · executive · guru — 이 화면에 나온 사람 기준
    followed: list[PeopleHomeRow]
    recorded: list[RecordedPerson]
    recorded_status: Literal["ok", "error"]   # 전제 원장 실패해도 팔로우·급증은 살린다(블록 단위)
    rising: list[PeopleHomeRow]
    as_of: str | None


class PersonResolve(BaseModel):
    entity_id: int | None
    name: str | None


class MergedName(BaseModel):
    entity_id: int
    name: str
    type: str                # person · company(회사로 잘못 분류됐던 이름)
    docs: int
    rule: str | None


class PersonDocRow(BaseModel):
    id: int
    title: str
    published_at: str | None
    source_type: str | None


class PersonFlowYear(BaseModel):
    year: str
    own: int
    cited: int


class PersonPremise(BaseModel):
    key: str
    claim: str
    status: PremiseStatus | None
    kind: str
    evidence: list[str]
    rule: str
    sources: list[EraSource]
    said_at: str | None      # 원문 중 가장 이른 날짜
    co_holders: list[WhoPerson]   # 같은 전제를 가진 다른 사람·기관


class PersonMentions(BaseModel):
    count: int
    first_at: str | None
    last_at: str | None


class PersonCoEntity(BaseModel):
    entity_id: int
    name: str
    link_type: str
    aliases: str | None
    count: int


class PersonRelationRow(BaseModel):
    id: int
    direction: str
    rel_type: str
    other_id: int
    other_name: str
    other_type: str
    other_aliases: str | None
    mechanism: str | None
    epistemic_type: str
    created_at: str | None
    narrative_topic: str | None
    narrative_title: str | None
    narrative_superseded: bool


class PersonProfileOut(BaseModel):
    status: str
    digest: str | None
    insights: str | None
    created_at: str | None


class PersonDetail(BaseModel):
    entity_id: int           # 대표 인물 id — 요청한 id가 묶인 이름이면 대표로 바뀐다
    requested_id: int
    name: str
    role: PersonRole | None
    merged_names: list[MergedName]
    following: bool
    mentions: PersonMentions
    own_docs: list[PersonDocRow]   # 본인 글(저자 연결)
    own_total: int
    own_source: str | None         # 본인 글 출처 표기(오크트리 메모)
    cited: list[PersonDocRow]      # 다른 사람이 인용·언급한 글(본인 글 제외, 최근)
    cited_total: int
    flow: list[PersonFlowYear]
    premises: list[PersonPremise]
    premises_status: Literal["ok", "error"]
    co_entities: list[PersonCoEntity]
    relations: list[PersonRelationRow]
    profile: PersonProfileOut | None
    profile_stale: bool
    new_since_profile: int | None
