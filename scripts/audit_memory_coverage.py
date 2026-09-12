"""Read-only corpus inventory; lexical candidates, never confirmed speakers/stance changes.

Run: python3 scripts/audit_memory_coverage.py
Private, regenerable output: logs/memory-coverage/latest.json
No app imports, model calls, network calls, or production DB mutations.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "hbm": r"\bHBM\w*|고대역폭\s*메모리",
    "dram": r"\b(?:DRAM|DDR[3456]?|LPDDR\w*|GDDR\w*)\b|디램|D램",
    "nand": r"\b(?:NAND|SSD|QLC|TLC)\b|낸드",
}
COMPANIES = {
    "samsung": r"삼성전자|Samsung\s+(?:Electronics|Memory)",
    "sk_hynix": r"하이닉스|hynix|Solidigm|솔리다임",
    "micron": r"마이크론|\bMicron\b",
    "kioxia": r"키옥시아|기옥시아|\bKioxia\b",
    "sandisk": r"샌디스크|\bSandisk\b",
}


def source_key(row):
    kind = row["source_type"]
    if kind in ("youtube", "telegram"):
        return kind + ":" + row["source_id"].split("/")[0]
    u = urlparse(row["url"] or row["source_id"])
    host = (u.hostname or "unknown").removeprefix("www.")
    if host in ("blog.naver.com", "m.blog.naver.com"):
        path = u.path.strip("/").split("/")[0]
        author = parse_qs(u.query).get("blogId", [path])[0]
        return "blog:naver:" + author
    return "blog:" + host


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "backend/db/stock_explorer.db")
    ap.add_argument("--out", type=Path, default=ROOT / "logs/memory-coverage/latest.json")
    ap.add_argument("--as-of", default=datetime.now(timezone.utc).isoformat())
    args = ap.parse_args()
    cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        ap.error("--as-of requires timezone")
    if args.out.resolve() == args.db.resolve():
        ap.error("output cannot overwrite database")
    c = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA query_only=ON")
    c.execute("BEGIN")  # one consistent read snapshot
    registry = {}
    for table, kind, keycol, namecol in [
        ("youtube_channels", "youtube", "channel_id", "title"),
        ("telegram_channels", "telegram", "channel_name", "display_name"),
    ]:
        for r in c.execute("SELECT * FROM " + table):
            registry[kind + ":" + r[keycol]] = {"name": r[namecol], "registrations": [{"collect_enabled": r["collect_enabled"]}]}
    for r in c.execute("SELECT * FROM blog_sources WHERE is_active=1"):
        key = source_key({"source_type": "blog", "url": r["url"], "source_id": r["url"]})
        entry = registry.setdefault(key, {"name": r["blog_name"], "registrations": []})
        entry["registrations"].append({"url": r["url"], "name": r["blog_name"],
                                       "registered_author": r["author"], "collect_enabled": r["collect_enabled"]})
        if len(entry["registrations"]) > 1:
            entry["name"] = key + " (multiple feeds; not one author)"
    products = {k: re.compile(v, re.I) for k, v in PATTERNS.items()}
    companies = {k: re.compile(v, re.I) for k, v in COMPANIES.items()}
    groups = defaultdict(list)
    totals, quality = Counter(), Counter()
    for r in c.execute("SELECT * FROM raw_documents ORDER BY id"):
        totals[r["source_type"]] += 1
        if r["source_type"] not in ("blog", "telegram", "youtube"):
            continue
        derived = "원본 자막" in (r["raw_content"] or "") and "→ opus 정리본" in (r["raw_content"] or "")
        if r["source_type"] == "youtube":
            quality["youtube_derived_marker_all_docs"] += derived
        body = r["markdown"] or r["raw_content"] or ""
        text = (r["title"] or "") + "\n" + body
        tags = [k for k, p in products.items() if p.search(text)]
        if not tags:
            continue
        quality["candidate_docs"] += 1
        quality["candidate_derived_marker"] += derived
        quality["empty_body"] += not bool(body.strip())
        quality["short_body_under_300"] += len(body.strip()) < 300
        date = None
        try:
            date = datetime.fromisoformat((r["published_at"] or "").replace("Z", "+00:00"))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
                quality["timezone_assumed_utc"] += 1
        except ValueError:
            quality["unknown_published_at"] += 1
        if date and date > cutoff:
            quality["after_cutoff"] += 1
            continue
        hits = []
        for p in products.values():
            m = p.search(body)
            if m:
                hits.append(body[max(0, m.start()-90):m.end()+250])
        groups[source_key(r)].append({
            "doc_id": r["id"], "title": r["title"], "url": r["url"],
            "published_at": r["published_at"], "fetched_at": r["fetched_at"],
            "day": date.date().isoformat() if date else None,
            "recent_30d": bool(date and cutoff-timedelta(days=30) <= date <= cutoff),
            "products": tags, "companies": [k for k,p in companies.items() if p.search(text)],
            "body_chars": len(body), "content_hash": r["content_hash"],
            "digest_status": r["digest_status"], "excerpts": hits,
            "derived_marker": derived,
            "raw_starts": (r["raw_content"] or "")[:100],
        })
    results = []
    for key, docs in groups.items():
        days = sorted({d["day"] for d in docs if d["day"]})
        results.append({"source_key": key, **registry.get(key, {"name": key}),
                        "count": len(docs), "days": len(days),
                        "first": days[0] if days else None, "last": days[-1] if days else None,
                        "recent_30d": sum(d["recent_30d"] for d in docs),
                        "products": dict(Counter(t for d in docs for t in d["products"])),
                        "company_mentions": dict(Counter(t for d in docs for t in d["companies"])),
                        "docs": docs})
    results.sort(key=lambda x: (-x["recent_30d"], -x["days"], x["source_key"]))
    output = {"as_of": cutoff.isoformat(), "method": "lexical product hits in title + markdown-or-raw; not semantic labels or confirmed authors; products overlap",
              "patterns": PATTERNS, "company_patterns": COMPANIES, "totals": dict(totals),
              "quality": dict(quality), "sources": results}
    c.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"as_of":output["as_of"], "totals":output["totals"], "quality":output["quality"],
                      "sources":[{k:v for k,v in s.items() if k != "docs"} for s in results]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
