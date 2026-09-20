#!/usr/bin/env python3
"""Prepare/run/resume a local A/B/C Weekly writing experiment. No publishing."""
import argparse
import fcntl
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from models.weekly_reader import ComparisonRequest
from pipeline.weekly.reader_experiment import run
from pipeline.weekly.reader_fork import fork
from pipeline.weekly.reader_packet import prepare
from pipeline.weekly.research import prepare_research
from pipeline.weekly.store import atomic_write, dumps, now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="Freeze a deliberately selected development evidence packet")
    for field in ("request-key", "source-run-id", "week-start", "week-end", "outlook-start", "outlook-end", "selection"):
        prep.add_argument("--" + field, required=True)
    prep.add_argument("--model", default="opus")
    prep.add_argument("--workflow", choices=("comparison", "briefing"), default="comparison")
    prep.add_argument("--effort", choices=("low", "medium", "high"), default="high")
    prep.add_argument("--call-timeout", type=int, default=360)
    prep.add_argument("--max-seconds", type=int, default=2100)
    for command in ("run", "resume", "status", "cancel"):
        action = sub.add_parser(command)
        action.add_argument("--request-key", required=True)
        if command in {"run", "resume"}:
            action.add_argument("--completion-engine", choices=("default", "codex-exec"))
            action.add_argument("--completion-model")
    research = sub.add_parser("research", help="Reopen a comparison's frozen corpus for question-led research")
    research.add_argument("--request-key", required=True, help="Existing comparison request")
    research.add_argument("--new-request-key", required=True)
    research.add_argument("--max-seconds", type=int, default=7200)
    clone = sub.add_parser("fork", help="Reuse frozen evidence and exact A/B calls for a new review experiment")
    clone.add_argument("--request-key", required=True, help="Existing source request")
    clone.add_argument("--new-request-key", required=True)
    clone.add_argument("--reuse-reviews", action="store_true", help="Also reuse B reviews; the complete review inputs must still match")
    clone.add_argument("--reuse-draft", action="store_true", help="Reuse the C draft for host validation fixes; final reviews always run again")
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "prepare":
        selection = json.loads(Path(args.pop("selection")).read_text())
        print(prepare(ComparisonRequest(**args), selection))
        return
    # Validate the path component through the same contract without trusting CLI paths.
    import re
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", args["request_key"]):
        parser.error("Invalid request key")
    directory = ROOT / "logs" / "weekly-harness" / "comparisons" / args["request_key"]
    if not (directory / "manifest.json").exists():
        parser.error("Prepare this request first")
    if command == "research":
        print(prepare_research(directory, args["new_request_key"], max_seconds=args["max_seconds"]))
    elif command == "fork":
        print(fork(directory, args["new_request_key"], reuse_reviews=args["reuse_reviews"], reuse_draft=args["reuse_draft"]))
    elif command == "status":
        print((directory / "manifest.json").read_text())
    elif command == "cancel":
        atomic_write(directory / "cancel.requested", now())
        print("취소 요청을 기록했습니다")
    else:
        if args.get("completion_engine") or args.get("completion_model"):
            with (directory / ".run.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    parser.error("진행 중인 실행의 모델 설정은 바꿀 수 없습니다")
                manifest = json.loads((directory / "manifest.json").read_text())
                if manifest["status"] == "completed":
                    parser.error("완료된 실행은 새 분기로 준비하세요")
                settings = {k: args[k] for k in ("completion_engine", "completion_model") if args.get(k)}
                request = ComparisonRequest.model_validate({**manifest["request"], **settings})
                manifest.setdefault("completion_changes", []).append({"at": now(), "previous": manifest["request"], "settings": settings})
                manifest["request"] = request.model_dump(mode="json")
                atomic_write(directory / "manifest.json", dumps(manifest))
        if command == "resume":
            # Never revoke cancellation while the original worker is still exiting.
            with (directory / ".run.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    parser.error("기존 실행이 종료된 후 resume 하세요. 취소 요청은 유지했습니다")
                (directory / "cancel.requested").unlink(missing_ok=True)
        print(dumps(run(directory)))


if __name__ == "__main__":
    main()
