"""Fixed subprocess entrypoints with process-group timeout/cancellation.

No model-authored code, shell command, Python expression, or arbitrary URL handler.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


class Cancelled(Exception):
    pass


def isolated(kind, payload, *, timeout, cancelled=lambda: False):
    env = dict(os.environ)
    backend = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = backend
    proc = subprocess.Popen([sys.executable, "-m", "pipeline.weekly.worker", kind],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=backend, env=env, start_new_session=True)
    started = time.monotonic()
    request = json.dumps(payload, ensure_ascii=False)
    try:
        while True:
            if cancelled():
                raise Cancelled("취소 요청")
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError(f"{kind} 실행 시간 상한 초과")
            try:
                stdout, stderr = proc.communicate(input=request, timeout=min(1, remaining))
                break
            except subprocess.TimeoutExpired:
                request = None
        if proc.returncode:
            # Remote errors can contain API-key query strings; never persist stderr verbatim.
            raise RuntimeError(f"{kind} worker 실패 (exit {proc.returncode}); 공급자 응답 또는 인증을 확인하세요")
        marker = "\nWEEKLY_RESULT="
        if marker not in stdout:
            raise RuntimeError(f"{kind} worker가 구조화된 결과를 반환하지 않았습니다")
        result = json.loads(stdout.rsplit(marker, 1)[1])
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe:
                pipe.close()


def main():
    payload = json.load(sys.stdin)
    try:
        if sys.argv[1] == "model":
            if payload.pop("engine", None) == "codex-exec":
                from pipeline.weekly.codex_completion import run
                result = run(**payload)
                print("\nWEEKLY_RESULT=" + json.dumps({"result": result}, ensure_ascii=False, allow_nan=False))
                return
            from dataclasses import asdict
            from pipeline.llm import run
            from pipeline.enrich import llm_engine
            enforced = llm_engine() == "claude-code" and payload.get("json_schema") is not None
            if not enforced:
                payload.pop("json_schema", None)
            result = asdict(run(**payload))
            result["structured_output_enforced"] = enforced
        elif sys.argv[1] == "source":
            from pipeline.weekly.sources import acquire
            result = acquire(**payload)
        else:
            raise ValueError("unknown worker")
        print("\nWEEKLY_RESULT=" + json.dumps({"result": result}, ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        # Only controlled error messages leave provider workers. SDK errors may include secrets.
        message = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: 공급자 요청 실패"
        print("\nWEEKLY_RESULT=" + json.dumps({"error": message}, ensure_ascii=False))


if __name__ == "__main__":
    main()
