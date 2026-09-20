"""Tool-free Claude CLI adapter. Does not use the application's LLM/DB helpers."""
from __future__ import annotations

import json
import math
import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from models.market_analysis import ModelAction
from .store import secure_directory
from .process_guard import guarded_command


class ModelError(RuntimeError):
    def __init__(self, message: str, cost_usd: float | None = None):
        super().__init__(message)
        self.cost_usd = cost_usd


class ModelCancelled(ModelError):
    pass


@dataclass
class ModelReply:
    action: ModelAction
    cost_usd: float


def kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    # The leader may have exited while descendants remain.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    process.wait(timeout=5)


class ClaudeModel:
    def __init__(self, cwd: Path, executable: str | None = None, model: str | None = None):
        self.cwd = secure_directory(cwd)
        # Explicit host configuration wins over PATH; never retry using a less
        # restrictive CLI when the selected executable lacks isolation flags.
        self.executable = executable or os.getenv("MARKET_ANALYSIS_CLI") or shutil.which("claude")
        self.model = model or os.getenv("MARKET_ANALYSIS_MODEL", "sonnet")
        self._checked = False

    def _preflight(self):
        if not self.executable:
            raise ModelError("Claude CLI를 찾을 수 없습니다. MARKET_ANALYSIS_CLI에 실행 파일의 절대 경로를 지정해 주세요.", 0)
        if not self._checked:
            try:
                result = subprocess.run([self.executable, "--help"], capture_output=True, text=True,
                                        cwd=self.cwd, timeout=15, close_fds=True)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ModelError(f"Claude CLI 실행 확인 실패: {self.executable}. MARKET_ANALYSIS_CLI 경로를 확인해 주세요.", 0) from exc
            flags = ("--safe-mode", "--tools", "--strict-mcp-config", "--setting-sources",
                     "--disable-slash-commands", "--no-session-persistence", "--max-budget-usd")
            missing = [flag for flag in flags if flag not in result.stdout]
            if result.returncode or missing:
                reason = "누락된 격리 옵션: " + ", ".join(missing) if missing else f"도움말 종료 코드: {result.returncode}"
                raise ModelError(f"Claude CLI 확인 실패: {self.executable}. {reason}. "
                                 "격리를 지원하는 실행 파일을 MARKET_ANALYSIS_CLI로 지정해 주세요.", 0)
            self._checked = True

    def command(self, system: str, budget: float) -> list[str]:
        return [self.executable, "-p", "--output-format", "json", "--model", self.model,
                "--safe-mode", "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--setting-sources", "", "--settings", '{"disableAllHooks":true,"enabledPlugins":{}}',
                "--disable-slash-commands", "--no-chrome", "--no-session-persistence",
                "--permission-mode", "dontAsk", "--max-budget-usd", f"{budget:.6f}",
                "--system-prompt", system, "--json-schema", json.dumps(ModelAction.model_json_schema())]

    def call(self, system: str, context: dict, *, budget: float, timeout: float,
             cancel: Callable[[], bool]) -> ModelReply:
        self._preflight()
        if cancel():
            raise ModelCancelled("분석이 취소되었습니다.", 0)
        # Keep authentication in this trusted host process. No app secrets or
        # configuration overrides are inherited by the isolated Python runtime.
        keep = {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR",
                "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}
        env = {k: v for k, v in os.environ.items() if k in keep}
        env.update({"CLAUDE_CODE_SAFE_MODE": "1", "DISABLE_AUTOUPDATER": "1"})
        data = json.dumps(context, ensure_ascii=False, allow_nan=False).encode()
        # Input is a regular trusted file to avoid blocking on a large pipe write.
        input_path = self.cwd / "request.json"
        from .store import atomic_write
        atomic_write(input_path, data)
        with input_path.open("rb") as stdin:
            command = guarded_command(self.cwd, self.command(system, budget), timeout + 1)
            process = subprocess.Popen(command, stdin=stdin,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.cwd,
                                       env=env, close_fds=True, start_new_session=True)
        selector = selectors.DefaultSelector()
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        for name in buffers:
            stream = getattr(process, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        started = time.monotonic()
        try:
            while selector.get_map():
                if cancel():
                    raise ModelCancelled("분석이 취소되었습니다. 호출 비용은 확인되지 않았습니다.")
                if time.monotonic() - started > timeout:
                    raise ModelError("모델 호출 시간이 초과되었습니다. 호출 비용은 확인되지 않았습니다.")
                for key, _ in selector.select(.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffers[key.data].extend(chunk)
                    if sum(len(v) for v in buffers.values()) > 2 * 1024 * 1024:
                        raise ModelError("모델 출력 크기 제한을 초과했습니다.")
            process.wait(timeout=5)
        finally:
            selector.close()
            kill_group(process)
            process.stdout.close()
            process.stderr.close()
        try:
            result = json.loads(buffers["stdout"])
        except (ValueError, TypeError) as exc:
            raise ModelError("모델이 유효한 JSON 응답을 반환하지 않았습니다.") from exc
        cost = result.get("total_cost_usd")
        if not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
            raise ModelError("모델 비용을 확인할 수 없어 추가 호출을 중단했습니다.")
        if process.returncode or result.get("is_error"):
            raise ModelError("모델 호출이 실패했습니다: " + str(result.get("result", ""))[:1000], cost)
        raw = result.get("structured_output")
        try:
            if raw is None:
                raw = json.loads(result["result"])
            action = ModelAction.model_validate(raw)
        except (ValueError, TypeError, KeyError) as exc:
            raise ModelError("모델 액션이 검증 스키마와 일치하지 않습니다.", cost) from exc
        return ModelReply(action=action, cost_usd=float(cost))


def structured_call(system: str, context: dict, schema: dict, *, budget: float, timeout: float,
                    model: str | None = None) -> tuple[dict, float]:
    """One tool-free CLI call that must return JSON matching `schema`. Returns (payload, cost_usd).

    Shares the audited isolation flags of ClaudeModel; used by host features that need a
    structured answer without the CodeAct loop (question refinement, research synthesis).
    """
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="explorer-structured-") as directory:
        cwd = Path(directory).resolve(strict=True)
        adapter = ClaudeModel(cwd, model=model)
        adapter._preflight()
        command = adapter.command(system, budget)
        command[command.index("--json-schema") + 1] = json.dumps(schema)
        keep = {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}
        env = {k: v for k, v in os.environ.items() if k in keep}
        env.update({"CLAUDE_CODE_SAFE_MODE": "1", "DISABLE_AUTOUPDATER": "1"})
        path = cwd / "request.json"
        path.write_bytes(json.dumps(context, ensure_ascii=False, allow_nan=False).encode())
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 1:
            raise ModelError("모델 호출 시간이 남지 않았습니다.", 0)
        with path.open("rb") as stdin:
            # Guard fires one second after our own deadline so the loop reports the timeout.
            process = subprocess.Popen(guarded_command(cwd, command, remaining + 1), stdin=stdin,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env,
                                       close_fds=True, start_new_session=True)
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        selector = selectors.DefaultSelector()
        try:
            for name in buffers:
                stream = getattr(process, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                if time.monotonic() - started > timeout:
                    raise ModelError("모델이 시간 제한 안에 응답하지 않았습니다. 호출 비용은 미확인입니다.")
                for key, _ in selector.select(.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffers[key.data].extend(chunk)
                    if sum(map(len, buffers.values())) > 2 * 1024 * 1024:
                        raise ModelError("모델 출력 크기 제한을 초과했습니다.")
            process.wait(timeout=5)
        finally:
            selector.close()
            kill_group(process)
            process.stdout.close()
            process.stderr.close()
    try:
        response = json.loads(buffers["stdout"])
    except (ValueError, TypeError) as exc:
        detail = buffers["stderr"].decode(errors="replace").strip()[:300]
        raise ModelError(f"모델이 JSON을 반환하지 않았습니다 (종료 코드 {process.returncode})." + (f" stderr: {detail}" if detail else "")) from exc
    cost = response.get("total_cost_usd")
    if not isinstance(cost, (int, float)) or isinstance(cost, bool) or not math.isfinite(cost) or cost < 0:
        raise ModelError("모델 비용을 확인할 수 없습니다.")
    if process.returncode or response.get("is_error"):
        raise ModelError("모델 호출 실패: " + str(response.get("result", ""))[:500], cost)
    raw = response.get("structured_output")
    if raw is None:
        try:
            raw = json.loads(response["result"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ModelError("모델 결과 형식이 올바르지 않습니다.", cost) from exc
    return raw, float(cost)
