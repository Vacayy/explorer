"""Repeat a review experiment on the same evidence and exact cached A/B inputs."""
import fcntl
import hashlib
import json
import shutil
from pathlib import Path

from models.weekly_reader import ComparisonRequest
from .store import atomic_write, digest, dumps, now


def fork(source_directory, request_key, *, reuse_reviews=False, reuse_draft=False):
    source = Path(source_directory).resolve()
    with (source / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("원본 실행 종료 후 비교를 복제하세요") from exc
        original = json.loads((source / "manifest.json").read_text())
        request = ComparisonRequest.model_validate(dict(original["request"], request_key=request_key))
        packet = json.loads((source / "packet.json").read_text())
        selection = json.loads((source / "selection.json").read_text())
        if digest(packet) != original["packet_sha256"]:
            raise ValueError("원본 입력 hash 불일치")
        files = [*sorted((source / "evidence").glob("*.json")), *sorted((source / "charts").glob("*.svg"))]
        hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        if original.get("evidence_files") != hashes:
            raise ValueError("원본 보관 자료 hash 불일치")
        directory = source.parent / request.request_key
        directory.mkdir()  # Existing experiments must never be overwritten.
        config = request.model_dump(mode="json")
        manifest = {"identity": digest({"request": config, "selection": selection}), "request": config,
                    "status": "preparing", "created_at": now(), "inherited_from": source.name,
                    "packet_sha256": original["packet_sha256"], "evidence_files": hashes,
                    "source_corpus_sha256": original.get("source_corpus_sha256"),
                    "source_count": len(packet["sources"]), "document_count": original["document_count"],
                    "expert_quality": "not_evaluated", "calls": {}, "inherited_stages": []}
        atomic_write(directory / "manifest.json", dumps(manifest))
        for path in [source / "packet.json", source / "selection.json", *files]:
            target = directory / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        # Reviews are inherited only when explicitly requested. The runner still
        # verifies the complete model payload for every cached call.
        stages = ["single", "judgment", "judged", "single-structure-repair", "judged-structure-repair"]
        if reuse_reviews or reuse_draft:
            stages += ["judged-facts", "judged-investor"]
        if reuse_draft:
            stages += ["reviewed-judgment", "reviewed"]
        for stage in stages:
            cache = source / "calls" / f"{stage}.json"
            if cache.exists():
                record = json.loads(cache.read_text())
                if record.get("parsed") is None:
                    continue
                if stage.endswith("-structure-repair"):
                    variant = source / (stage.removesuffix("-structure-repair") + ".json")
                    if not variant.exists() or json.loads(variant.read_text()) != record["parsed"]:
                        continue
                if digest(record["payload"]) != record["input_sha256"]:
                    raise ValueError("보관 호출 입력 hash 불일치: " + stage)
                atomic_write(directory / "calls" / cache.name, dumps(record))
                manifest["calls"][stage] = dict(original["calls"][stage], reused_from=source.name)
                manifest["inherited_stages"].append(stage)
        manifest.update(status="prepared", prepared_at=now())
        atomic_write(directory / "manifest.json", dumps(manifest))
        return directory
