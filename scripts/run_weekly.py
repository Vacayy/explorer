#!/usr/bin/env python3
"""Run/read/cancel/resume a Weekly experiment without starting the operating server."""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from models.weekly import ResumeRequest, RunRequest
from pipeline.weekly.evidence import Evidence
from pipeline.weekly.runner import Runner
from pipeline.weekly.store import Store


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["run", "prepare", "status", "cancel", "recover", "resume", "list"])
    ap.add_argument("--run-id")
    ap.add_argument("--request-key")
    ap.add_argument("--cutoff", help="ISO8601 with timezone; omit for a live capture now")
    ap.add_argument("--mode", choices=["live", "public_reconstruction", "system_replay"], default="live")
    ap.add_argument("--replay-run-id")
    ap.add_argument("--scope")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--reviewer-model", default="opus")
    ap.add_argument("--max-steps", type=int, default=24)
    ap.add_argument("--max-tool-calls", type=int, default=40)
    ap.add_argument("--max-seconds", type=int, default=1800)
    ap.add_argument("--review-rounds", type=int, default=2)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--extra-steps", type=int, default=8)
    ap.add_argument("--extra-seconds", type=int, default=900)
    ap.add_argument("--source-db", type=Path)
    ap.add_argument("--store-db", type=Path)
    ap.add_argument("--runs-dir", type=Path)
    args = ap.parse_args()
    store = Store(args.store_db, args.runs_dir, args.source_db)
    if args.command == "list":
        print(json.dumps(store.list_runs(), ensure_ascii=False, indent=2))
        return 0
    if args.command in {"status", "cancel", "recover", "resume"}:
        if not args.run_id:
            ap.error("--run-id가 필요합니다")
        if args.command == "resume":
            store.resume(args.run_id, ResumeRequest(extra_steps=args.extra_steps, extra_seconds=args.extra_seconds))
            result = Runner(store).execute(args.run_id)
        else:
            result = {"cancel": store.cancel, "recover": store.recover, "status": store.get}[args.command](args.run_id)
    else:
        kwargs = dict(request_key=args.request_key or uuid.uuid4().hex, mode=args.mode,
                      replay_run_id=args.replay_run_id, model=args.model, reviewer_model=args.reviewer_model,
                      max_steps=args.max_steps, max_tool_calls=args.max_tool_calls, max_seconds=args.max_seconds,
                      review_rounds=args.review_rounds, allow_network=not args.offline)
        if args.scope:
            kwargs["scope"] = args.scope
        if args.cutoff:
            kwargs["cutoff"] = args.cutoff
        request = RunRequest(**kwargs)
        run_id, created = store.create(request)
        print(f"Weekly run: {run_id}", flush=True)
        if args.command == "prepare":
            run = store.get(run_id)
            evidence = Evidence(store.directory(run_id))
            replay = store.directory(args.replay_run_id) if args.replay_run_id else None
            cp = run["checkpoint"]
            cp["coverage"] = evidence.freeze(store.source_path, run["config"], replay_directory=replay)
            cp["corpus_sha256"] = evidence.file_hash()
            store.save(run_id, checkpoint=cp, status="partial", event=("prepared_without_model", cp["coverage"]))
            result = store.get(run_id)
        else:
            result = Runner(store).execute(run_id) if created else store.get(run_id)
    print(json.dumps({"id": result["id"], "status": result["status"], "error": result["error"],
                      "steps": result["checkpoint"]["steps"], "tool_calls": result["checkpoint"]["tool_calls"],
                      "elapsed_seconds": result["checkpoint"]["elapsed_seconds"],
                      "directory": str(store.directory(result["id"])), "artifacts": result["artifacts"]}, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"complete", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
