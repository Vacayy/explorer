# AGENTS.md — 이 저장소에서 일하는 AI 에이전트(Codex 등)에게

이 저장소의 작업 규칙 원본은 **`CLAUDE.md`** 하나다. 작업을 시작하기 전에 반드시 `CLAUDE.md`를 읽고 그대로 따른다(이 파일에 규칙을 따로 적지 않는다 — 두 곳에 두면 어긋난다).

- 시스템 지도: `docs/SYSTEM.md` · 스펙 목록: `docs/specs/README.md`
- 절차서(스킬): `.claude/skills/*/SKILL.md` — 해당 작업이면 먼저 읽는다. 특히
  - API를 만들거나 응답 모양을 바꾸거나, 화면에 "서버 응답 형식이 올바르지 않습니다"가 뜰 때: `.claude/skills/api-contract/SKILL.md`
  - 버그 수정·리팩토링·조사: `.claude/skills/engineering-playbooks/SKILL.md`
- 백엔드는 자동 재시작 없이 돈다. 백엔드 코드를 고쳤으면 사용자에게 재시작을 요청하고, 재시작 후 `cd frontend && npm run contracts:live`로 실제 응답을 검증한다.
