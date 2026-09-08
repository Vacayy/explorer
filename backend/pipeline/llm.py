"""공용 LLM 러너 — claude -p 하네스 격리 + 스트리밍 + 호출 기록 (D-130, docs/specs/chat-harness.md).

실측(2026-09-08, haiku·같은 프롬프트)으로 정한 규칙:
- **격리 cwd + `--setting-sources ""` + `--tools ""`**: 호출당 컨텍스트 21,889 → 6,576 토큰(−70%).
  repo cwd에서 돌리면 CLAUDE.md·훅·MCP·도구 정의가 매 콜 실려 간다. 도구가 필요한 호출(vision의 Read)만 tools를 명시.
- **구조화 출력은 `--json-schema`를 쓰지 않는다**: 모델이 답을 텍스트로 한 번, 구조화 도구로 한 번 더 써서
  output 526 → 2,061 토큰(4배)·지연 6 → 19초(3배)·2턴. 대신 본문 뒤 `---META---` 구분선 + JSON 한 줄(1턴)로 받고
  `split_meta()`로 나눈다. 스트리밍도 이 방식이라야 본문 델타가 그대로 흘러나온다.
- `--bare`는 API 키를 요구해 이 환경(키체인 구독 인증, D-106)에선 못 쓴다.
- 모든 호출을 `llm_calls`에 기록(usage·cost·소요) — 비용 결정은 유추하지 말고 실측한다(D-117 교훈).

ANTHROPIC_API_KEY가 있으면 API 모드(system 파라미터·스트리밍 동일 인터페이스).
"""
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pipeline.enrich import _claude_bin, llm_engine

# 격리 실행 디렉토리 — CLAUDE.md·.claude/ 가 없는 빈 폴더 (repo 루트 .claude-runtime/, gitignore)
RUNTIME_DIR = Path(__file__).resolve().parent.parent.parent / ".claude-runtime"
META_MARKER = "---META---"

API_MODELS = {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-5", "opus": "claude-opus-5"}

OnText = Callable[[str], None]


@dataclass
class LLMResult:
    text: str
    model: str                      # 요청 티어 (haiku|sonnet|opus)
    engine: str                     # claude-code | api
    usage: dict = field(default_factory=dict)
    cost_usd: float | None = None
    duration_ms: int = 0
    session_id: str | None = None

    @property
    def label(self) -> str:
        return f"{self.engine}/{self.model}"


def run(prompt: str, *, system: str | None = None, model: str = "sonnet",
        effort: str | None = None, tools: tuple[str, ...] = (), timeout: int = 300,
        job: str = "", on_text: OnText | None = None) -> LLMResult:
    """LLM 1회 호출. on_text가 있으면 본문 델타를 스트리밍으로 넘긴다(반환값은 동일).

    tools: 빈 튜플이면 도구 전부 비활성(기본). 필요한 것만 명시(예: ("Read",)).
    """
    eng = llm_engine()
    if eng is None:
        raise RuntimeError("LLM 엔진 없음 (ENRICH_ENGINE=claude-code 또는 ANTHROPIC_API_KEY 필요)")
    t0 = time.time()
    err = None
    try:
        if eng == "claude-code":
            res = _run_claude_code(prompt, system=system, model=model, effort=effort,
                                   tools=tools, timeout=timeout, on_text=on_text)
        else:
            res = _run_api(prompt, system=system, model=model, on_text=on_text)
        res.duration_ms = res.duration_ms or int((time.time() - t0) * 1000)
        return res
    except Exception as e:  # noqa: BLE001 — 기록 후 그대로 올린다
        err = f"{type(e).__name__}: {str(e)[:300]}"
        raise
    finally:
        _record(job, model, eng, effort, locals().get("res"), int((time.time() - t0) * 1000), err)


# ── claude-code ──────────────────────────────────────────────────────────────

def _argv(model: str, effort: str | None, tools: tuple[str, ...], system: str | None,
          stream: bool) -> list[str]:
    argv = [_claude_bin(), "-p", "--model", model,
            "--setting-sources", "",          # 사용자·프로젝트 설정(훅·MCP) 미로드
            "--tools", ",".join(tools),       # ""=도구 전부 끔 → 도구 정의 토큰 제거
            "--no-session-persistence"]
    if effort:
        argv += ["--effort", effort]
    if system:
        argv += ["--append-system-prompt", system]
    if stream:
        argv += ["--output-format", "stream-json", "--verbose", "--include-partial-messages"]
    else:
        argv += ["--output-format", "json"]
    return argv


def _run_claude_code(prompt, *, system, model, effort, tools, timeout, on_text) -> LLMResult:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    argv = _argv(model, effort, tools, system, stream=on_text is not None)
    if on_text is None:
        proc = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                              timeout=timeout, cwd=RUNTIME_DIR)
        if proc.returncode != 0:
            # claude는 오류(사용량 한도·미로그인)를 stdout에 쓴다
            raise RuntimeError(f"claude -p 실패 rc={proc.returncode} "
                               f"out={proc.stdout.strip()[:200]!r} err={proc.stderr.strip()[:120]!r}")
        env = json.loads(proc.stdout)
        return _from_result_event(env, model, env.get("result", ""))

    # 스트리밍: stdout 라인 단위 이벤트, 텍스트 델타를 on_text로
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=RUNTIME_DIR)
    killer = threading.Timer(timeout, proc.kill)
    killer.start()
    parts: list[str] = []
    final: dict | None = None
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "stream_event":
                delta = (ev.get("event") or {}).get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    parts.append(delta["text"])
                    on_text(delta["text"])
            elif ev.get("type") == "result":
                final = ev
        proc.wait()
    finally:
        killer.cancel()
    if final is None:
        raise RuntimeError(f"claude -p 스트림 결과 없음 rc={proc.returncode} "
                           f"err={(proc.stderr.read() or '').strip()[:200]!r}")
    if final.get("is_error"):
        raise RuntimeError(f"claude -p 오류: {str(final.get('result'))[:200]}")
    return _from_result_event(final, model, "".join(parts) or final.get("result", ""))


def _from_result_event(env: dict, model: str, text: str) -> LLMResult:
    u = env.get("usage") or {}
    return LLMResult(
        text=text, model=model, engine="claude-code",
        usage={
            "input": u.get("input_tokens"),
            "cache_create": u.get("cache_creation_input_tokens"),
            "cache_read": u.get("cache_read_input_tokens"),
            "output": u.get("output_tokens"),
            "thinking": (u.get("output_tokens_details") or {}).get("thinking_tokens"),
        },
        cost_usd=env.get("total_cost_usd"),
        duration_ms=env.get("duration_ms") or 0,
        session_id=env.get("session_id"),
    )


# ── API ──────────────────────────────────────────────────────────────────────

def _run_api(prompt, *, system, model, on_text) -> LLMResult:
    import anthropic
    client = anthropic.Anthropic()
    kw = dict(model=API_MODELS.get(model, model), max_tokens=4096,
              messages=[{"role": "user", "content": prompt}])
    if system:
        kw["system"] = system
    if on_text is None:
        msg = client.messages.create(**kw)
        text = "".join(b.text for b in msg.content if b.type == "text")
        usage = msg.usage
    else:
        parts = []
        with client.messages.stream(**kw) as stream:
            for t in stream.text_stream:
                parts.append(t)
                on_text(t)
            usage = stream.get_final_message().usage
        text = "".join(parts)
    return LLMResult(text=text, model=model, engine="api",
                     usage={"input": usage.input_tokens, "output": usage.output_tokens})


# ── 기록 ─────────────────────────────────────────────────────────────────────

def _record(job, model, engine, effort, res: LLMResult | None, duration_ms, err):
    """llm_calls 적재 — 기록 실패가 호출 경로를 깨면 안 된다."""
    try:
        from database import get_connection
        u = (res.usage if res else {}) or {}
        conn = get_connection()
        conn.execute("""
            INSERT INTO llm_calls (job, model, engine, effort, input_tokens, cache_create_tokens,
                                   cache_read_tokens, output_tokens, thinking_tokens, cost_usd,
                                   duration_ms, ok, error)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (job or None, model, engine, effort, u.get("input"), u.get("cache_create"),
             u.get("cache_read"), u.get("output"), u.get("thinking"),
             res.cost_usd if res else None, duration_ms, 1 if err is None else 0, err))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── 출력 파싱 ─────────────────────────────────────────────────────────────────

def split_meta(text: str) -> tuple[str, dict | None]:
    """`본문 ---META--- {json}` → (본문, meta). 구분선이 없거나 JSON이 깨지면 (전체, None)."""
    if not text:
        return "", None
    idx = text.rfind(META_MARKER)
    if idx < 0:
        return text.strip(), None
    body, tail = text[:idx].rstrip(), text[idx + len(META_MARKER):]
    meta = extract_json(tail)
    return body, meta


def extract_json(text: str) -> dict | None:
    """텍스트 속 첫 `{`~마지막 `}` JSON — 설명 문장이 앞뒤에 붙어도 건진다."""
    if not text:
        return None
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        data = json.loads(text[s:e + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def visible_text(streamed: str) -> str:
    """스트리밍 누적 텍스트에서 사용자에게 보일 본문만 — META 구분선(부분 포함) 이후는 감춘다."""
    idx = streamed.find(META_MARKER)
    if idx >= 0:
        return streamed[:idx].rstrip()
    # 구분선이 반쯤 도착한 상태("---ME")도 숨긴다
    m = re.search(r"-{2,}M?E?T?A?-{0,3}$", streamed)
    return streamed[:m.start()].rstrip() if m else streamed
