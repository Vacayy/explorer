"""Freeze source versions before ranking; never query mutable enrichments."""
import json
import re
import shutil
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .store import atomic_write, digest, dumps, now

UTC = timezone.utc
SERIES_META = {
    "index_sp500": ("S&P 500", "index points", "price", "America/New_York", "16:00"),
    "index_nasdaq": ("NASDAQ Composite", "index points", "price", "America/New_York", "16:00"),
    "index_dow": ("Dow Jones", "index points", "price", "America/New_York", "16:00"),
    "index_kospi": ("KOSPI", "index points", "price", "Asia/Seoul", "15:30"),
    "index_kosdaq": ("KOSDAQ", "index points", "price", "Asia/Seoul", "15:30"),
    "index_hsi": ("Hang Seng", "index points", "price", "Asia/Hong_Kong", "16:00"),
    "index_nikkei": ("Nikkei 225", "index points", "price", "Asia/Tokyo", "15:30"),
    "index_twii": ("Taiwan weighted", "index points", "price", "Asia/Taipei", "13:30"),
    "macro_us2y": ("US 2-year Treasury yield", "percent", "yield", None, None),
    "macro_us10y": ("US 10-year Treasury yield", "percent", "yield", None, None),
    "vix": ("VIX", "index points", "level", None, None),
    "fear_greed": ("Fear & Greed", "score (0–100)", "level", None, None),
    "macro_gold": ("Gold futures", "USD / troy oz", "price", None, None),
    "macro_oil": ("WTI futures", "USD / barrel", "price", None, None),
    "macro_dxy": ("US Dollar index", "index points", "price", None, None),
    "macro_hyg": ("HYG ETF", "USD / share", "price", "America/New_York", "16:00"),
    "macro_btc": ("BTC/USD", "USD / BTC", "price", None, None),
    "macro_usdkrw": ("USD/KRW", "KRW / USD", "price", None, None),
}


def instant(value, *, sqlite_utc=False):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC) if sqlite_utc else None
        return dt.astimezone(UTC)
    except ValueError:
        return None


def publication_bound(value):
    """Date-only, timezone unknown: conservative end of day in UTC−12."""
    if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return datetime.fromisoformat(value).replace(tzinfo=UTC) + timedelta(hours=36), "date_only_upper_bound"
        except ValueError:
            return None, "invalid"
    dt = instant(value)
    return dt, "timestamp" if dt else "unknown_timezone_or_date"


def observation_bound(day, series):
    info = SERIES_META.get(series)
    if series.startswith("us:"):
        info = (series[3:], "USD / share", "price", "America/New_York", "16:00")
    if info and info[3]:
        # Conservative on early closes. This is a bound, not an exchange calendar.
        return datetime.fromisoformat(day + "T" + info[4]).replace(tzinfo=ZoneInfo(info[3])).astimezone(UTC)
    return datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(hours=36)


@contextmanager
def readonly(path):
    c = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA query_only=ON")
        yield c
    finally:
        c.close()


def source_text(row, transcript=None):
    raw = row.get("raw_content") or ""
    kind = "stored_source"
    if row["source_type"] == "youtube":
        if transcript:
            return transcript, "stored_transcript"
        if row.get("digest_status") == "ok":
            return row.get("markdown") or raw, "derived_summary"
        kind = "stored_transcript"
    if not raw.strip():
        return row.get("markdown") or "", "stored_markdown_unverified"
    if re.search(r"<(?:html|div|p|article)\b", raw, re.I):
        soup = BeautifulSoup(raw, "html.parser")
        for el in soup(["script", "style", "noscript"]):
            el.decompose()
        return soup.get_text("\n", strip=True), "html_text"
    return raw, kind


def make_item(item_id, kind, meta, data, text=""):
    result = {"id": item_id, "kind": kind, "meta": meta, "data": data, "text": text}
    result["sha256"] = digest(result)
    return result


def verify_item(item):
    if digest({k: v for k, v in item.items() if k != "sha256"}) != item["sha256"]:
        raise ValueError(f"근거 hash 불일치: {item['id']}")


class Evidence:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "corpus.sqlite"

    def freeze(self, source_path, config, *, replay_directory=None):
        if self.path.exists():
            return self.coverage()
        cutoff = instant(config["cutoff"])
        if replay_directory:
            old = Evidence(replay_directory)
            manifest = old.coverage()
            if instant(manifest["frozen_at"]) > cutoff:
                raise ValueError("원본 snapshot은 cutoff 이후에 확보됐습니다")
            if manifest["mode"] not in {"live", "system_replay"}:
                raise ValueError("재구성 자료를 system replay로 승격할 수 없습니다")
            if instant(manifest["cutoff"]) > cutoff:
                raise ValueError("원본 snapshot의 cutoff가 요청보다 늦습니다")
            shutil.copyfile(old.path, self.path)
            atomic_write(self.directory / "snapshot.json", dumps({**manifest, "replay_source": str(old.directory),
                         "requested_cutoff": config["cutoff"], "corpus_sha256": self.file_hash()}))
            # Copy only the original frozen corpus. Later calculations/fetches are not replay inputs.
            return manifest
        floor = cutoff - timedelta(days=config["lookback_days"])
        counts, excluded = Counter(), Counter()
        tmp = self.directory / "corpus.preparing.sqlite"
        tmp.unlink(missing_ok=True)
        self.directory.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(tmp)
        try:
            target.executescript("""
            CREATE TABLE items(id TEXT PRIMARY KEY,kind TEXT NOT NULL,meta TEXT NOT NULL,data TEXT NOT NULL,text TEXT NOT NULL,sha256 TEXT NOT NULL);
            CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,title,text,tokenize='unicode61');
            CREATE TABLE manifest(data TEXT NOT NULL);
            """)
            with readonly(source_path) as source:
                source.execute("BEGIN")
                tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                transcripts = {}
                if "youtube_digest_jobs" in tables:
                    transcripts = {r["doc_id"]: r["transcript"] for r in source.execute("SELECT doc_id,transcript FROM youtube_digest_jobs WHERE transcript IS NOT NULL")}
                calls = {}
                if "transcripts" in tables:
                    calls = {r["raw_doc_id"]: r["call_date"] for r in source.execute("SELECT raw_doc_id,call_date FROM transcripts")}
                for row in source.execute("SELECT * FROM raw_documents ORDER BY id"):
                    raw = dict(row)
                    pub, precision = publication_bound(raw.get("published_at"))
                    fetched = instant(raw.get("fetched_at"), sqlite_utc=True)
                    if pub is None or pub > cutoff or pub < floor:
                        excluded["publication_unknown_after_cutoff_or_outside_lookback"] += 1
                        continue
                    if config["mode"] == "live" and (fetched is None or fetched > cutoff):
                        excluded["not_collected_by_cutoff"] += 1
                        continue
                    call_date = calls.get(raw["id"])
                    if call_date and call_date[:10] > cutoff.date().isoformat():
                        excluded["future_transcript_call_date"] += 1
                        continue
                    text, kind = source_text(raw, transcripts.get(raw["id"]))
                    if not text.strip():
                        excluded["no_readable_source"] += 1
                        continue
                    normalized = re.sub(r"\s+", " ", text).strip()
                    meta = {"title": raw.get("title") or "제목 없음", "source_type": raw["source_type"],
                            "source_id": raw.get("source_id"), "url": raw.get("url"),
                            "published_at": raw.get("published_at"), "available_at_bound": pub.isoformat(),
                            "fetched_at": raw.get("fetched_at"), "time_precision": precision,
                            "content_kind": kind, "lineage": raw.get("url") or f"{raw['source_type']}:{raw.get('source_id')}",
                            "duplicate_group": digest(normalized), "call_date": call_date,
                            "temporal_status": "captured_live" if config["mode"] == "live" else "historical_version_unverified",
                            "warnings": ["수집한 출처의 주장입니다. 원 출처·인용 관계는 별도 검토합니다."]}
                    if raw["source_type"] == "transcript":
                        meta["warnings"].append("레거시 call_date는 회계분기로 추정됐을 수 있으며 published_at도 수집 시각일 수 있습니다. 원문으로 확인하기 전 실제 개최·공개 시각으로 사용하지 마세요.")
                    self._insert(target, make_item(f"d{raw['id']}", "document", meta, raw, text))
                    counts[raw["source_type"]] += 1
                series = {}
                for table, name_col, date_col in [("market_indicators", "indicator", "snapshot_date"), ("us_prices", "stock_code", "trade_date")]:
                    if table not in tables:
                        continue
                    for row in source.execute(f"SELECT * FROM {table} WHERE {date_col}<=? ORDER BY {date_col}", (cutoff.date().isoformat(),)):
                        raw = dict(row)
                        name = ("us:" if table == "us_prices" else "") + raw[name_col]
                        day = raw[date_col]
                        if day < floor.date().isoformat():
                            continue
                        if name not in SERIES_META and not name.startswith("us:"):
                            excluded["indicator_definition_or_vintage_unavailable"] += 1
                            continue
                        if observation_bound(day, name) > cutoff:
                            excluded["unfinished_or_time_uncertain_observation"] += 1
                            continue
                        fetched = instant(raw.get("fetched_at"), sqlite_utc=True)
                        if config["mode"] == "live" and fetched and fetched > cutoff:
                            continue
                        value = raw.get("close") if table == "us_prices" else raw.get("value")
                        if not isinstance(value, (float, int)):
                            continue
                        series.setdefault(name, []).append({"date": day, "value": value, "volume": raw.get("volume"), "raw": raw})
                for name, points in series.items():
                    info = SERIES_META.get(name, (name[3:], "USD / share", "price", "America/New_York", "16:00"))
                    meta = {"title": info[0], "unit": info[1], "metric_kind": info[2],
                            "source_type": "local_prices" if name.startswith("us:") else "local_indicators",
                            "series": name, "population": name, "adjustment": "legacy_store_not_verified",
                            "temporal_status": "captured_live" if config["mode"] == "live" else "historical_version_unverified",
                            "warnings": ["수집 당시 공급자 버전·조정 방식 미검증. 실제 마지막 관측일을 확인하세요.",
                                         "관측일은 발표일과 다릅니다. 장 마감 경계는 조기 폐장에 보수적인 상한입니다."]}
                    self._insert(target, make_item("s-" + name.replace(":", "-"), "series", meta, {"points": points}))
                manifest = {"version": 1, "cutoff": config["cutoff"], "mode": config["mode"],
                            "frozen_at": now(), "source": str(Path(source_path).resolve()),
                            "documents": dict(counts), "excluded": dict(excluded), "series_count": len(series),
                            "lookback_days": config["lookback_days"],
                            "limitations": ["운영 원문은 수정 이력 미보존: historical_version_unverified를 확정 과거 근거로 승격하지 않습니다.",
                                            "정확한 텍스트 중복을 묶지만 재전파·번역의 독립성은 논증 검토가 필요합니다.",
                                            "보존 차트 이미지의 시각 해석 및 전체 거래소 캘린더는 미연결입니다."]}
                target.execute("INSERT INTO manifest VALUES(?)", (dumps(manifest),))
                target.commit()
            target.close()
            tmp.replace(self.path)
            atomic_write(self.directory / "snapshot.json", dumps({**manifest, "corpus_sha256": self.file_hash()}))
            return manifest
        finally:
            target.close()

    @staticmethod
    def _insert(conn, item):
        conn.execute("INSERT INTO items VALUES(?,?,?,?,?,?)", (item["id"], item["kind"], dumps(item["meta"]), dumps(item["data"]), item["text"], item["sha256"]))
        if item["kind"] == "document":
            conn.execute("INSERT INTO search VALUES(?,?,?)", (item["id"], item["meta"]["title"], item["text"]))

    def file_hash(self):
        import hashlib
        with self.path.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    def coverage(self):
        with readonly(self.path) as c:
            return json.loads(c.execute("SELECT data FROM manifest").fetchone()[0])

    def get(self, item_id):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", item_id):
            raise ValueError("잘못된 evidence id")
        external = self.directory / "evidence" / f"{item_id}.json"
        if external.exists():
            item = json.loads(external.read_text())
        else:
            with readonly(self.path) as c:
                row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if row is None:
                raise KeyError(item_id)
            item = dict(row)
            item["data"], item["meta"] = json.loads(item["data"]), json.loads(item["meta"])
        verify_item(item)
        return item

    def add(self, kind, meta, data, text=""):
        item_id = "x-" + digest({"kind": kind, "meta": meta, "data": data, "text": text})[:24]
        item = make_item(item_id, kind, meta, data, text)
        path = self.directory / "evidence" / f"{item_id}.json"
        if not path.exists():
            atomic_write(path, dumps(item))
        return item

    def find(self, query="", *, limit=10, offset=0, source=None, since=None):
        with readonly(self.path) as c:
            filters, args = ["i.kind='document'", "json_extract(i.meta,'$.temporal_status')!='historical_version_unverified'"], []
            if source:
                filters.append("json_extract(i.meta,'$.source_type')=?")
                args.append(source)
            if since:
                filters.append("json_extract(i.meta,'$.available_at_bound')>=?")
                args.append(since)
            if query.strip():
                tokens = re.findall(r"[\w가-힣]+", query)[:12]
                if not tokens:
                    return {"items": [], "total": 0}
                # Substring fallback is over the already eligible frozen corpus, never global top-k.
                filters.append("(" + " OR ".join("(i.text LIKE ? OR json_extract(i.meta,'$.title') LIKE ?)" for _ in tokens) + ")")
                for token in tokens:
                    escaped = token.replace("%", "").replace("_", "")
                    args.extend([f"%{escaped}%"] * 2)
                match = " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)
                ranked = {r[0]: r[1] for r in c.execute("SELECT id,bm25(search) FROM search WHERE search MATCH ?", (match,))}
            else:
                tokens, ranked = [], {}
            rows = c.execute("SELECT i.id,i.meta,i.text FROM items i WHERE " + " AND ".join(filters), args).fetchall()
        candidates = []
        for row in rows:
            meta = json.loads(row["meta"])
            matches = sum(t.casefold() in (meta["title"] + " " + row["text"]).casefold() for t in tokens)
            candidates.append((matches, -ranked.get(row["id"], 0), meta["available_at_bound"], row, meta))
        candidates.sort(key=lambda r: r[:3], reverse=True)
        groups, results = set(), []
        for _, _, _, row, meta in candidates:
            if meta["duplicate_group"] in groups:
                continue
            groups.add(meta["duplicate_group"])
            pos = next((row["text"].casefold().find(t.casefold()) for t in tokens if t.casefold() in row["text"].casefold()), 0)
            results.append({"id": row["id"], "meta": meta, "length": len(row["text"]),
                            "excerpt_start": max(0, pos - 150), "excerpt": row["text"][max(0, pos - 150):pos + 650]})
        return {"items": results[offset:offset + limit], "total_unique_texts": len(results), "next_offset": offset + limit if offset + limit < len(results) else None,
                "note": "검색 발췌만으로 원문을 읽은 것으로 간주하지 않습니다. read_evidence로 확인하세요."}

    def series(self):
        with readonly(self.path) as c:
            ids = [r[0] for r in c.execute("SELECT id FROM items WHERE kind='series'")]
        ids += [p.stem for p in (self.directory / "evidence").glob("*.json") if json.loads(p.read_text())["kind"] == "series"]
        return [item for item_id in dict.fromkeys(ids) if (item := self.get(item_id))["meta"].get("temporal_status") != "historical_version_unverified"]
