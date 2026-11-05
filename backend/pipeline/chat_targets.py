"""AI 대화 › 대상 붙이기 (ia-redesign §4.14a, D-311) — 후보 검색 · 대상 해석 · 붙인 대상의 근거 수집.

대화 입력의 `@`·'＋'·⌘K 'AI에게 묻기'로 붙인 대상은 `{kind, ref, label}`로 오고
`conversations.state_json.attached_refs`에 대화 내내 남는다. 답변 때는 이름을 추측하지 않고
식별자(ref)로 기존 도구 함수를 바로 불러 근거를 모은다. 모델 호출은 없다.
"""
import json
import sqlite3

KINDS = ("stock", "us_stock", "narrative", "question", "doc", "person", "theme", "peer_group", "report")
KIND_LABEL = {"stock": "국내 종목", "us_stock": "미국 종목", "narrative": "서사", "question": "질문", "doc": "자료",
              "person": "인물", "theme": "테마·업종", "peer_group": "Peer 그룹", "report": "리포트"}
MAX_NEW_PER_MESSAGE = 5      # 한 번에 붙이는 새 대상 (시안 '5개까지')
MAX_ATTACHED = 12            # 대화에 남는 대상 상한
ALL_LIMIT = 4                # '전체' 보기의 종류별 후보 수
KIND_LIMIT = 20              # 종류를 고른 보기의 후보 수
EVIDENCE_TOTAL = 12          # 붙인 대상 근거의 상한 — 라우터가 고른 도구가 들어갈 자리를 남긴다(MAX_EVIDENCE 20)
SOURCE_LABEL = {"telegram": "텔레그램", "blog": "블로그", "youtube": "유튜브", "news": "뉴스", "transcript": "컨콜",
                "scrap": "스크랩", "article": "아티클", "canon": "인물", "memo": "메모", "history": "역사"}
REPORT_CODE = {"11013": "1분기", "11012": "2분기", "11014": "3분기", "11011": "연간"}


def _safe(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:   # 선택 테이블이 없는 설치
        return []


def _day(value) -> str | None:
    return str(value)[:10] if value else None


def _target(kind, ref, label, *, sub=None, date=None, code=None, change_pct=None, available=True) -> dict:
    return {"kind": kind, "ref": str(ref), "label": str(label or ref)[:200], "sub": sub, "date": date,
            "code": code, "change_pct": change_pct, "available": available}


# ── Peer 그룹 (게시본 파일 — DB가 아님) ───────────────────────────────────────

def _peer_runtime():
    from routers.peers import read_runtime
    return read_runtime()


def _peer_returns(runtime, codes: list[str]) -> dict[int, float | None]:
    """그룹 동일가중 5·20·60거래일 수익률(%) — 값이 없는 종목은 뺀다."""
    out = {}
    for days in (5, 20, 60):
        rets = []
        for code in codes:
            series = [p for p in runtime.prices.prices.get(code, []) if p]
            if len(series) > days:
                rets.append((series[-1] / series[-1 - days] - 1) * 100)
        out[days] = sum(rets) / len(rets) if rets else None
    return out


def _peer_members(runtime, group_id: str) -> list:
    return [c for c in runtime.catalog.companies if group_id in c.groupIds]


def _peer_target(runtime, group) -> dict:
    members = _peer_members(runtime, group.id)
    r20 = _peer_returns(runtime, [m.code for m in members])[20]
    sub = f"{len(members)}개사" + (f" · 20일 {r20:+.1f}%" if r20 is not None else "")
    return _target("peer_group", group.id, group.name, sub=sub, change_pct=r20)


# ── 후보 검색 ─────────────────────────────────────────────────────────────────

def _search_kind(conn, kind: str, q: str, limit: int) -> list[dict]:
    from routers import spine_search as ss
    like = f"%{q}%"
    if kind == "stock":
        if not q:
            return []
        return [_target("stock", c["stock_code"], c["name"], code=c["stock_code"], change_pct=c["change_pct"], date=c["price_date"],
                        sub=" · ".join(x for x in (c["stock_code"], c["sector"], c["market"]) if x))
                for c in ss._companies(conn, q, limit)]
    if kind == "us_stock":
        if not q:
            return []
        return [_target("us_stock", u["ticker"], u["name"], code=u["ticker"],
                        sub=" · ".join(x for x in (u["ticker"], u["group_label"]) if x)) for u in ss._us(conn, q, limit)]
    if kind in ("person", "theme"):
        if not q:
            return []
        types = ("person",) if kind == "person" else ("theme", "sector")
        rows = _safe(conn, f"""SELECT id, type, name FROM entities WHERE status = 'active' AND type IN ({",".join("?" * len(types))})
            AND name LIKE ? ORDER BY CASE WHEN name = ? THEN 0 WHEN name LIKE ? THEN 1 ELSE 2 END, name LIMIT ?""",
                     (*types, like, q, f"{q}%", limit))
        return [_target(kind, r["id"], r["name"], sub={"person": "인물", "theme": "테마", "sector": "업종"}[r["type"]]) for r in rows]
    if kind == "narrative":
        rows = _safe(conn, """SELECT topic, title, created_at FROM narratives
            WHERE superseded_at IS NULL AND COALESCE(kind, 'topic') = 'topic' AND (topic LIKE ? OR title LIKE ?)
            ORDER BY CASE WHEN topic = ? THEN 0 WHEN topic LIKE ? THEN 1 ELSE 2 END, created_at DESC LIMIT ?""",
                     (like, like, q, f"{q}%", limit))
        return [_target("narrative", r["topic"], r["topic"], sub=r["title"], date=_day(r["created_at"])) for r in rows]
    if kind == "question":
        num = q.lstrip("#")
        rows = _safe(conn, """SELECT q.id, q.text, q.lead_verdict, q.updated_at,
                (SELECT COUNT(*) FROM sub_questions s WHERE s.question_id = q.id) n_sub
            FROM questions q WHERE q.status != 'dismissed' AND (q.text LIKE ? OR CAST(q.id AS TEXT) = ?)
            ORDER BY CASE WHEN CAST(q.id AS TEXT) = ? THEN 0 ELSE 1 END, q.updated_at DESC LIMIT ?""", (like, num, num, limit))
        return [_target("question", r["id"], r["text"], code=f"#{r['id']}", date=_day(r["updated_at"]),
                        sub=" · ".join(x for x in (_verdict_ko(r["lead_verdict"]), f"서브질문 {r['n_sub']}") if x)) for r in rows]
    if kind == "doc":
        rows = _safe(conn, """SELECT id, title, source_type, published_at FROM raw_documents
            WHERE title IS NOT NULL AND title != '' AND title LIKE ? ORDER BY published_at DESC LIMIT ?""", (like, limit))
        return [_target("doc", r["id"], r["title"], sub=SOURCE_LABEL.get(r["source_type"], r["source_type"]), date=_day(r["published_at"]))
                for r in rows]
    if kind == "report":
        rows = _safe(conn, """SELECT r.anchor_topic, r.title, r.created_at FROM reports r
            JOIN (SELECT anchor_topic, MAX(id) mid FROM reports GROUP BY anchor_topic) t ON t.mid = r.id
            WHERE r.anchor_topic LIKE ? OR r.title LIKE ? ORDER BY r.created_at DESC LIMIT ?""", (like, like, limit))
        return [_target("report", r["anchor_topic"], r["anchor_topic"], sub=r["title"], date=_day(r["created_at"])) for r in rows]
    if kind == "peer_group":
        try:
            runtime = _peer_runtime()
        except (OSError, ValueError, KeyError, TypeError):
            return []
        ql = q.lower()
        hits = []
        for g in runtime.catalog.groups:
            members = _peer_members(runtime, g.id)
            if not q or ql in g.name.lower() or any(ql in m.name.lower() or q == m.code for m in members):
                hits.append((0 if g.name.lower().startswith(ql) else 1, g))
        hits.sort(key=lambda x: x[0])
        return [_peer_target(runtime, g) for _, g in hits[:limit]]
    return []


def _verdict_ko(v: str | None) -> str | None:
    return {"leaning_yes": "선행 예", "leaning_no": "선행 아니오", "mixed": "선행 혼조", "unknown": "선행 미정"}.get(v or "")


def search(conn, q: str, kind: str | None = None) -> list[dict]:
    """[{kind, items}] — kind가 없으면 종류별 ALL_LIMIT개, 있으면 그 종류만 KIND_LIMIT개."""
    q = (q or "").strip()
    kinds = (kind,) if kind else KINDS
    limit = KIND_LIMIT if kind else ALL_LIMIT
    return [{"kind": k, "items": items} for k in kinds if (items := _search_kind(conn, k, q, limit))]


# ── 대상 해석 (지금도 있는가 · 표시 정보) ─────────────────────────────────────

def resolve(conn, ref: dict) -> dict:
    """저장된 {kind, ref, label} → 표시용 대상. 사라졌으면 available=False(보관된 서사·지운 자료)."""
    kind, key, label = ref.get("kind"), str(ref.get("ref") or ""), ref.get("label") or ref.get("ref")
    gone = _target(kind, key, label, available=False)
    if kind == "stock":
        row = conn.execute("SELECT corp_name, sector, market FROM companies WHERE stock_code = ?", (key,)).fetchone()
        if not row:
            return gone
        px = _safe(conn, "SELECT trade_date, close FROM stock_prices WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 2", (key,))
        chg = (px[0]["close"] / px[1]["close"] - 1) * 100 if len(px) == 2 and px[0]["close"] and px[1]["close"] else None
        return _target("stock", key, row["corp_name"], code=key, change_pct=chg, date=_day(px[0]["trade_date"]) if px else None,
                       sub=" · ".join(x for x in (key, row["sector"], row["market"]) if x))
    if kind == "us_stock":
        row = (_safe(conn, "SELECT ticker, company_name FROM transcript_follow WHERE ticker = ?", (key,))
               or _safe(conn, "SELECT ticker, ticker company_name FROM us_fundamentals WHERE ticker = ?", (key,))
               or _safe(conn, "SELECT stock_code ticker, stock_code company_name FROM us_prices WHERE stock_code = ? LIMIT 1", (key,)))
        return _target("us_stock", key, row[0]["company_name"] or key, code=key, sub=key) if row else gone
    if kind in ("person", "theme"):
        row = conn.execute("SELECT id, type, name FROM entities WHERE id = ? AND status = 'active'", (int(key) if key.isdigit() else -1,)).fetchone()
        ok = row and ((kind == "person" and row["type"] == "person") or (kind == "theme" and row["type"] in ("theme", "sector")))
        return _target(kind, key, row["name"], sub={"person": "인물", "theme": "테마", "sector": "업종"}[row["type"]]) if ok else gone
    if kind == "narrative":
        row = conn.execute("""SELECT topic, title, created_at FROM narratives WHERE topic = ? AND superseded_at IS NULL
            ORDER BY version DESC LIMIT 1""", (key,)).fetchone()
        return _target("narrative", key, key, sub=row["title"], date=_day(row["created_at"])) if row else gone
    if kind == "question":
        row = conn.execute("SELECT id, text, updated_at FROM questions WHERE id = ? AND status != 'dismissed'",
                           (int(key) if key.isdigit() else -1,)).fetchone()
        return _target("question", key, row["text"], code=f"#{row['id']}", date=_day(row["updated_at"])) if row else gone
    if kind == "doc":
        row = conn.execute("SELECT id, title, source_type, published_at FROM raw_documents WHERE id = ?",
                           (int(key) if key.isdigit() else -1,)).fetchone()
        return _target("doc", key, row["title"] or label, sub=SOURCE_LABEL.get(row["source_type"], row["source_type"]),
                       date=_day(row["published_at"])) if row else gone
    if kind == "report":
        row = conn.execute("SELECT anchor_topic, title, created_at FROM reports WHERE anchor_topic = ? ORDER BY id DESC LIMIT 1", (key,)).fetchone()
        return _target("report", key, key, sub=row["title"], date=_day(row["created_at"])) if row else gone
    if kind == "peer_group":
        try:
            runtime = _peer_runtime()
        except (OSError, ValueError, KeyError, TypeError):
            return gone
        group = next((g for g in runtime.catalog.groups if g.id == key), None)
        return _peer_target(runtime, group) if group else gone
    return gone


def merge_refs(previous: list[dict], incoming: list[dict], max_new: int = MAX_NEW_PER_MESSAGE) -> tuple[list[dict], list[dict]]:
    """클라이언트가 보낸 '지금 붙어 있는 전체 목록'을 정리한다 → (저장할 목록, 이번에 새로 붙은 것).

    같은 (kind, ref)는 한 번만. 새 대상이 max_new를 넘으면 ValueError(조용히 자르지 않는다)."""
    seen, out = set(), []
    for r in incoming:
        key = (r["kind"], str(r["ref"]))
        if key in seen or r["kind"] not in KINDS or not str(r["ref"]).strip():
            continue
        seen.add(key)
        out.append({"kind": r["kind"], "ref": str(r["ref"]).strip(), "label": str(r.get("label") or r["ref"])[:200]})
    before = {(r.get("kind"), str(r.get("ref"))) for r in previous or []}
    new = [r for r in out if (r["kind"], r["ref"]) not in before]
    if len(new) > max_new:
        raise ValueError(f"한 번에 붙일 수 있는 대상은 {max_new}개입니다")
    if len(out) > MAX_ATTACHED:
        raise ValueError(f"대화에 붙일 수 있는 대상은 {MAX_ATTACHED}개입니다")
    return out, new


# ── 프롬프트 블록 · 근거 수집 ─────────────────────────────────────────────────

REF_HINT = {"stock": "종목코드", "us_stock": "티커", "narrative": "서사 topic", "question": "질문 번호", "doc": "doc_id",
            "person": "엔티티 id", "theme": "엔티티 id", "peer_group": "Peer 그룹 id", "report": "리포트 topic"}


def prompt_block(refs: list[dict]) -> str | None:
    """'[대화에 붙인 대상]' — 라우터·종합 입력. 사용자가 고른 대상이라 이름 해석이 끝나 있다."""
    if not refs:
        return None
    lines = ["[대화에 붙인 대상] 사용자가 목록에서 직접 고른 대상이다. 이름을 추측하지 말고 아래 식별자를 그대로 쓴다. "
             "기본 자료(종목: 시세·공시·실적·최근 자료 / 미국 종목: 도시에 요약·컨콜 / 서사: 최신 버전·인과 고리 / 질문: 판정·서브질문·지표 관측 / "
             "인물·테마: 최근 자료 / Peer 그룹: 구성·성과 / 리포트: 본문 / 자료: 본문)는 이미 근거에 들어 있다. 질문이 더 요구할 때만 도구를 추가한다. "
             "'이것·이 종목·이 서사' 같은 지시어는 이 대상을 가리킨다."]
    for r in refs:
        lines.append(f"- {KIND_LABEL.get(r['kind'], r['kind'])} · {str(r.get('label') or '')[:80]} · {REF_HINT.get(r['kind'], 'ref')}={str(r['ref'])[:80]}")
    return "\n".join(lines)


def _tool_items(call: dict) -> list[dict]:
    from pipeline.chat_tools import run_tool
    return run_tool(call).items


def _financial_item(conn, code: str, name: str) -> dict | None:
    """최근 보고 기간의 매출·영업이익(손익계산서, 연결 우선)과 최신 PER·PBR. 분기 보고서의 손익은 단일 분기 값이다(D-183)."""
    corp = conn.execute("SELECT corp_code FROM companies WHERE stock_code = ?", (code,)).fetchone()
    lines = []
    if corp:
        last = _safe(conn, """SELECT bsns_year, reprt_code, fs_div FROM financial_statements
            WHERE corp_code = ? AND sj_div IN ('IS', 'CIS') AND account_nm IN ('매출액', '영업이익')
            ORDER BY bsns_year DESC, CASE reprt_code WHEN '11011' THEN 4 WHEN '11014' THEN 3 WHEN '11012' THEN 2 ELSE 1 END DESC,
                     CASE fs_div WHEN 'CFS' THEN 0 ELSE 1 END LIMIT 1""", (corp["corp_code"],))
        if last:
            y, rc, fs = last[0]["bsns_year"], last[0]["reprt_code"], last[0]["fs_div"]
            for r in _safe(conn, """SELECT account_nm, thstrm_amount FROM financial_statements WHERE corp_code = ? AND bsns_year = ?
                    AND reprt_code = ? AND fs_div = ? AND sj_div IN ('IS', 'CIS') AND account_nm IN ('매출액', '영업이익')""",
                           (corp["corp_code"], y, rc, fs)):
                try:
                    amt = float(str(r["thstrm_amount"]).replace(",", ""))
                    lines.append(f"{y} {REPORT_CODE.get(rc, rc)} {r['account_nm']} {amt / 1e8:,.0f}억원 ({'연결' if fs == 'CFS' else '별도'})")
                except (TypeError, ValueError):
                    continue
    val = _safe(conn, "SELECT trade_date, per, pbr FROM fundamentals WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 1", (code,))
    if val:
        v = val[0]
        lines.append(f"{v['trade_date']} PER {v['per'] if v['per'] is not None else '-'} · PBR {v['pbr'] if v['pbr'] is not None else '-'}")
    if not lines:
        return None
    return {"kind": "financials", "title": f"{name}({code}) 실적·밸류 요약", "text": "\n".join(lines), "date": None,
            "doc_id": None, "href": f"/analyze/{code}/financials"}


def _us_dossier_item(conn, ticker: str, name: str) -> dict | None:
    """미국 종목 도시에 요약 — 저장된 기본 지표만 읽는다(외부 조회 없음)."""
    row = conn.execute("SELECT data_json, fetched_at FROM us_fundamentals WHERE ticker = ?", (ticker,)).fetchone()
    if not row:
        return None
    try:
        f = json.loads(row["data_json"] or "{}")
    except ValueError:
        return None
    keys = [("price", "주가"), ("market_cap", "시가총액"), ("trailing_pe", "PER"), ("fwd_pe", "선행 PER"), ("revenue", "매출"),
            ("net_income", "순이익"), ("fcf", "FCF")]
    parts = [f"{label} {f[k]:,.2f}" if isinstance(f.get(k), float) and abs(f[k]) < 1e4 else f"{label} {f[k]:,.0f}"
             for k, label in keys if isinstance(f.get(k), (int, float))]
    if not parts:
        return None
    return {"kind": "dossier", "title": f"{name}({ticker}) 도시에 요약 (저장 {str(row['fetched_at'])[:10]})", "text": " · ".join(parts),
            "date": _day(row["fetched_at"]), "doc_id": None, "href": f"/us/{ticker}"}


def _question_item(qid: int) -> dict | None:
    from pipeline.questions import get_tree
    t = get_tree(qid)
    if t.get("error"):
        return None
    lines = [f"상태 {t.get('status')} · 선행 판정 {t.get('lead_verdict') or '-'} · 확정 판정 {t.get('confirm_verdict') or '-'}"
             + (f" · 괴리 {t['divergence']}" if t.get("divergence") else "")]
    if t.get("verdict_summary"):
        lines.append(f"판정 요약: {t['verdict_summary'][:300]}")
    for sq in t.get("sub_questions") or []:
        lines.append(f"- 서브질문: {sq['text'][:120]} (판정 {sq.get('verdict') or '-'})")
        for p in (sq.get("proxies") or [])[:3]:
            obs = (p.get("observations") or [])[:1]
            last = (f"최근 관측 {obs[0].get('observed_at')} {obs[0].get('value_num') if obs[0].get('value_num') is not None else obs[0].get('value_text') or ''}"
                    f" {obs[0].get('direction') or ''}".strip()) if obs else "관측 없음"
            lines.append(f"  · 지표 {p.get('label') or p.get('key')}: {last} (관측 {p.get('obs_count', 0)}건)")
    return {"kind": "question", "title": f"질문 #{qid} {t['text'][:70]}", "text": "\n".join(lines)[:2400],
            "date": _day(t.get("updated_at")), "doc_id": None, "href": f"/question/{qid}"}


def _peer_item(group_id: str) -> dict | None:
    try:
        runtime = _peer_runtime()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    group = next((g for g in runtime.catalog.groups if g.id == group_id), None)
    if not group:
        return None
    members = _peer_members(runtime, group.id)
    rets = _peer_returns(runtime, [m.code for m in members])
    lines = [f"묶은 기준: {group.interpretation}",
             "그룹 동일가중 수익률: " + " · ".join(f"{d}일 {v:+.1f}%" if v is not None else f"{d}일 -" for d, v in rets.items())]
    for m in members[:20]:
        r20 = _peer_returns(runtime, [m.code])[20]
        lines.append(f"- {m.name}({m.code}) 20일 {f'{r20:+.1f}%' if r20 is not None else '-'} · {', '.join(m.products[:3])}")
    return {"kind": "peer_group", "title": f"Peer 그룹 {group.name} ({len(members)}개사, 가격 기준일 {runtime.prices.asOf})",
            "text": "\n".join(lines)[:2400], "date": str(runtime.prices.asOf), "doc_id": None, "href": f"/discover/peers?group={group.id}"}


def _report_item(conn, topic: str) -> dict | None:
    row = conn.execute("SELECT id, title, body, created_at FROM reports WHERE anchor_topic = ? ORDER BY id DESC LIMIT 1", (topic,)).fetchone()
    if not row:
        return None
    from pipeline.chat_tools import BODY_CHARS
    return {"kind": "report", "title": f"리포트 · {topic} — {row['title'] or ''}"[:160], "text": (row["body"] or "")[:BODY_CHARS * 2],
            "date": _day(row["created_at"]), "doc_id": None, "href": f"/report?topic={topic}"}


def target_evidence(conn, ref: dict) -> list[dict]:
    """대상 하나의 기본 근거 — 기존 도구 함수(식별자로 호출)와 결정적 조회만 쓴다."""
    kind, key, label = ref["kind"], str(ref["ref"]), ref.get("label") or ref["ref"]
    if kind == "stock":
        items = _tool_items({"name": "get_quote", "args": {"stocks": [key]}})
        items += _tool_items({"name": "list_recent", "args": {"kind": "disclosures", "entity": key, "n": 3}})
        fin = _financial_item(conn, key, label)
        items += [fin] if fin else []
        items += _tool_items({"name": "list_recent", "args": {"kind": "docs", "entity": key, "days": 14, "n": 3}})
        return items
    if kind == "us_stock":
        dossier = _us_dossier_item(conn, key, label)
        return ([dossier] if dossier else []) + _tool_items({"name": "get_transcripts", "args": {"companies": [key], "n_per": 1}})
    if kind == "narrative":
        return _tool_items({"name": "get_narrative", "args": {"topic": key}}) + _tool_items({"name": "get_worldmodel", "args": {"entity": key}})
    if kind == "question":
        item = _question_item(int(key)) if key.isdigit() else None
        return [item] if item else []
    if kind in ("person", "theme"):
        return _tool_items({"name": "list_recent", "args": {"kind": "docs", "entity": label, "days": 30, "n": 4}})
    if kind == "peer_group":
        item = _peer_item(key)
        return [item] if item else []
    if kind == "report":
        item = _report_item(conn, key)
        return [item] if item else []
    return []    # doc — 본문은 attached_doc_ids 경로(attached_evidence)가 싣는다


def gather(conn, refs: list[dict]) -> tuple[list[dict], list[str]]:
    """붙인 대상 전부의 근거 → (근거 항목, 비어 있던 대상 이름). 대상마다 고르게 나눠 EVIDENCE_TOTAL을 넘지 않는다."""
    targets = [r for r in refs if r.get("kind") != "doc"]
    if not targets:
        return [], []
    per = max(2, EVIDENCE_TOTAL // len(targets))
    items, empty = [], []
    for r in targets:
        got = [it for it in target_evidence(conn, r) if it][:per]
        if not got:
            empty.append(f"{KIND_LABEL.get(r['kind'], r['kind'])} {r.get('label') or r['ref']}")
        for it in got:
            it["tool"] = "attached_targets"
        items.extend(got)
    return items[:EVIDENCE_TOTAL], empty
