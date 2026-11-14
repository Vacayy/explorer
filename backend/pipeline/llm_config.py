"""Host authentication and binary discovery shared by runner and availability gates."""
import os
import shutil


def _claude_bin() -> str | None:
    """노드 버전이 박힌 nvm 경로(.../v24.15.0/bin/claude)라 노드를 올리면 전 시스템의 LLM 호출이 죽는다.
    지정 경로가 실제로 없으면 PATH에서 찾아 자가 치유한다 (D-143, chatId=37 첫 질문 실패)."""
    env = os.getenv("CLAUDE_BIN")
    if env and os.path.exists(env):
        return env
    return shutil.which("claude") or env


def llm_engine() -> str | None:
    if os.getenv("ENRICH_ENGINE", "").strip().lower() == "claude-code":
        return "claude-code"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "api"
    return None
