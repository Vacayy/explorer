# Explorer

텔레그램·블로그·유튜브와 금융 데이터를 모아 읽고 공부하는 개인 투자 리서치 도구입니다.
관심 있는 투자자와 기업의 업데이트를 따라가고, 여러 자료에 하이라이트와 코멘트를 남기며 AI와 함께 살펴볼 수 있습니다.

기업의 실적뿐 아니라 사람들이 무엇을 기대하고 걱정하는지, 그 생각이 어제와 어떻게 달라졌는지에 관심을 두고 만들고 있습니다.
내가 읽는 소스와 공부한 기록을 꾸준히 쌓아두는 것이 이 프로젝트의 중심입니다.

## 주요 기능

- **시장 홈**: 주요 지수와 매크로 지표, 미국장 브리핑, 국장 거래대금 상위 종목의 관련 자료를 확인합니다.
- **내 피드**: 팔로우한 텔레그램·블로그·유튜브의 업데이트와 시스템이 정리한 기업·인물 요약을 함께 읽습니다.
- **저장됨과 스터디**: 다시 읽을 자료는 저장하고, 함께 공부할 자료는 별도의 스터디 프로젝트에 묶습니다. 문서에 표시한 하이라이트와 코멘트는 출처와 함께 노트에 남습니다.
- **문서 옆 AI 대화**: 읽던 문서를 켜둔 채 질문합니다. 선택한 인용과 코멘트를 바탕으로 설명을 듣거나, 관련 수집 자료를 찾고 웹 근거를 확인할 수 있습니다. 웹 확인은 Claude Code 엔진에서 지원합니다.
- **내러티브와 지식그래프**: 수집 자료에서 시장의 주요 이야기와 인과 주장을 정리하고, 관련 근거를 연결해 살펴봅니다.

메모리반도체를 대상으로 투자자 기대의 변화를 살피는 별도 실험 화면도 있습니다. 진행 범위는 [메모리반도체 커버리지](docs/specs/memory-semiconductor-coverage.md)에 정리했습니다.

## 시작하기

로컬 실행을 기준으로 합니다. Python 3.11 이상, Node.js 22.12 이상이 필요합니다.
LLM 기능에는 인증된 Claude Code CLI 또는 Anthropic API 키를 사용하며, 국내 공시·재무 수집에는 DART API 키가 필요합니다.

### 설치와 설정

```bash
git clone https://github.com/Vacayy/explorer.git
cd explorer
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
cp .env.example .env
```

`.env`에서 사용할 기능에 맞춰 설정합니다.

| 설정 | 용도 |
| --- | --- |
| `DART_API_KEY` | 국내 기업 공시·재무 수집 |
| `ENRICH_ENGINE=claude-code`, `CLAUDE_BIN` | Claude Code CLI 사용. `CLAUDE_BIN`에는 `which claude`로 확인한 절대경로 입력 |
| `ENRICH_ENGINE=api`, `ANTHROPIC_API_KEY` | CLI 대신 Anthropic API 사용 |
| `FRED_API_KEY`, `ALPHAVANTAGE_API_KEY`, `DATA_GO_KR_KEY` | 각각 FRED 데이터, 미국 실적 컨콜, 수출입 통계 수집 |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_CHAT_ID` | 텔레그램 브리핑·대화 봇 |

나머지 옵션은 [.env.example](.env.example)을 참고하세요. 별도 서버를 운영할 필요는 없지만, 사용하는 LLM의 구독료나 API 비용은 발생합니다.

### 초기 데이터

수집 데이터는 저장소에 포함하지 않습니다. 국내 기업·업종과 예시 커버리지를 채우려면 저장소 루트에서 다음을 실행합니다.

```bash
.venv/bin/python scripts/seed_companies.py
.venv/bin/python scripts/seed_sectors.py
.venv/bin/python scripts/seed_entities.py
.venv/bin/python scripts/seed_universe.py
.venv/bin/python scripts/ingest_prices.py
```

첫 주가 수집은 시간이 걸릴 수 있습니다. 커버리지를 직접 지정하려면 `scripts/universe.local.json`에 작성합니다. 이 파일은 Git에서 제외됩니다.

### 앱 실행

**터미널 두 개를 열고, 각각 저장소 루트에서 실행합니다.**

```bash
# 터미널 1: 백엔드
cd backend
../.venv/bin/uvicorn main:app --reload --port 8000
```

```bash
# 터미널 2: 프론트엔드
npm --prefix frontend run dev
```

브라우저에서 <http://localhost:5174>를 엽니다. 수집할 채널은 **Home → 피드 → 소스 관리**에서 등록합니다.

### 자동 수집 (macOS)

launchd로 수집·브리핑·백업 작업을 등록할 수 있습니다. 먼저 등록할 내용을 확인합니다.

```bash
.venv/bin/python scripts/install_launchd.py --dry-run
.venv/bin/python scripts/install_launchd.py
```

백업 작업을 사용하려면 아래의 `BACKUP_DIR`도 설정해야 합니다. 스케줄과 운영 방법은 [시스템 문서](docs/SYSTEM.md)를 참고하세요.

## 구조와 기술

소스에서 수집한 문서를 저장하고, LLM으로 태깅·요약한 뒤 검색과 읽기에 활용합니다.
내러티브 생성과 문서 추출에서 나온 인과 주장은 지식그래프에 쌓이며, 검토를 거친 지식은 이후 리서치에 사용됩니다.

자료에 근거한 사실과 AI의 해석을 구분하고, 발행 시점과 주장이 적용되는 시점을 함께 기록하는 것을 설계 원칙으로 삼습니다.
자동매매나 확정적인 가격 예측은 다루지 않습니다.

| 영역 | 기술 |
| --- | --- |
| 백엔드 | FastAPI · SQLite · Pydantic |
| 프론트엔드 | React · TypeScript · Vite · Tailwind CSS · shadcn/ui |
| 검색 | SQLite FTS5 · sqlite-vec · fastembed 로컬 임베딩 |
| AI | Claude Code CLI 또는 Anthropic API |
| 자동화 | Python 스크립트 · macOS launchd |

```text
backend/pipeline/   수집·정제·검색·리서치·스터디 로직
backend/routers/    API
frontend/src/      화면·공통 컴포넌트
scripts/           초기 데이터·수집 배치·백업
docs/              설계·운영 문서
```

## 데이터 보존과 한계

DB, 첨부 파일, 개인 노트는 Git에서 제외됩니다. 스터디 주석과 대화는 DB에 저장되며, Obsidian용 `vault/`는 별도로 관리합니다.
수집했던 과거 게시물이나 직접 작성한 노트는 다시 구할 수 없을 수 있으므로, 코드와 별개로 백업해야 합니다.

`.env`에 `BACKUP_DIR`를 지정한 뒤 실행합니다. 백업은 DB 무결성을 검사하며, `vault/`와 첨부 파일도 함께 보관합니다.

```bash
.venv/bin/python scripts/backup.py
.venv/bin/python scripts/backup.py --verify-only <파일.sqlite.gz>
```

기기 고장에 대비하려면 백업을 외장 디스크나 별도 저장소에도 보관하세요. 세부 동작은 [백업 스크립트](scripts/backup.py)에 설명돼 있습니다.

- 개인 로컬 사용을 전제로 하며, 다중 사용자 서비스는 지원하지 않습니다.
- 실행 중인 기기가 꺼지면 수집이 멈춥니다. 소스별 접근 범위와 API 제한에 따라 누락이나 지연이 생길 수 있습니다.
- 스터디에는 이미 수집한 자료를 추가하거나 본문을 붙여넣을 수 있습니다. 미수집 URL을 넣어 자동으로 가져오는 기능은 아직 없습니다.
- AI 요약과 인과 해석에는 오류가 있을 수 있습니다. 중요한 내용은 연결된 원문과 함께 확인해야 합니다.

## 문서

- [시스템 현황](docs/SYSTEM.md): 현재 구조와 운영 방법
- [기능별 스펙](docs/specs/README.md): 구현 범위와 진행 중인 설계
- [디자인 시스템](docs/DESIGN_SYSTEM.md): 레이아웃·타이포그래피·컴포넌트 규칙
- [설계 철학](docs/PHILOSOPHY.md) · [기술 결정 배경](docs/TECH_DECISIONS.md): 만들고자 하는 것과 선택의 이유
- [결정 이력](docs/DECISIONS.md): 변경된 결정과 그 배경

## 라이선스

코드는 [MIT](LICENSE) 라이선스입니다. 수집한 콘텐츠의 권리는 각 원저작자에게 있으며, 코드의 라이선스가 수집물에 적용되지는 않습니다.
