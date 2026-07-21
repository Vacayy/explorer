"""업사이드 모델 — 이벤트 → 수혜 종목의 조건부 업사이드/하방 정량 (action_thesis Phase 2).

앵커(주가·EPS·PER·매출·순이익률)를 결정적으로 수집한 뒤, opus가 사용자 정의 4단계
(매출 수혜 → 이익 → EPS → 적정주가; 불확실하면 멀티플 리레이팅)로 전개해 범위+조건부
시나리오를 낸다. point target 금지 — 시장은 반사적 도메인, 정직한 범위가 값지다 (D-034/D-035).
가정은 전부 assumptions에 명시(오라클 아님 — 사람이 검토·수정, ontology.md 원칙3).

결과는 models 테이블에 spec_json으로 적재 → 재현·감사·자동 리프레시 토대.
견고화(펜스 제거·재시도·출력전용 가드)는 scenario.py 패턴 재사용.
"""
import json
import os
import subprocess

from pipeline.enrich import _claude_bin, llm_engine

UPSIDE_MODEL = os.getenv("UPSIDE_MODEL", "opus")  # 다단 정량 추론 — 심층 종합 티어
TOP_DOCS = 8
EXCERPT = 700


def _anchor(conn, stock_code: str) -> dict:
    """결정적 앵커 수집 (LLM 0). 없는 값은 None으로 두고 LLM에 '미상' 전달."""
    price = shares = market_cap = eps = per = revenue = net_income = None
    net_margin = None

    p = conn.execute(
        "SELECT close, shares, market_cap FROM stock_prices "
        "WHERE stock_code=? ORDER BY trade_date DESC LIMIT 1", (stock_code,)).fetchone()
    if p:
        price, shares, market_cap = p["close"], p["shares"], p["market_cap"]

    f = conn.execute(
        "SELECT eps, per FROM fundamentals "
        "WHERE stock_code=? ORDER BY trade_date DESC LIMIT 1", (stock_code,)).fetchone()
    if f:
        eps, per = f["eps"], f["per"]
    if per is None and eps and price:  # PER 없으면 price/eps로 보완
        per = round(price / eps, 1)

    # 종목명: company 엔티티(aliases=종목코드) 우선, 없으면 companies.corp_name
    name_row = conn.execute(
        "SELECT name FROM entities WHERE type='company' AND aliases=? LIMIT 1",
        (stock_code,)).fetchone()
    name = name_row["name"] if name_row else None

    co = conn.execute(
        "SELECT corp_code, corp_name FROM companies WHERE stock_code=? LIMIT 1",
        (stock_code,)).fetchone()
    corp_code = co["corp_code"] if co else None
    if name is None and co:
        name = co["corp_name"]

    # 최근 연간(reprt_code='11011') 매출액·당기순이익 — CFS 우선, OFS fallback, 계정명 정규화
    if corp_code:
        from services.dart_service import _normalize_account_name, _parse_amount
        rows = conn.execute("""
            SELECT fs_div, account_nm, thstrm_amount FROM financial_statements
            WHERE corp_code=? AND reprt_code='11011' AND sj_div='IS'
              AND bsns_year=(SELECT max(bsns_year) FROM financial_statements
                             WHERE corp_code=? AND reprt_code='11011')""",
            (corp_code, corp_code)).fetchall()
        for fs_pref in ("CFS", "OFS"):  # CFS 우선
            sub = [r for r in rows if r["fs_div"] == fs_pref]
            if not sub:
                continue
            for r in sub:
                acc = _normalize_account_name(r["account_nm"])
                amt = _parse_amount(r["thstrm_amount"])
                if acc == "매출액" and revenue is None:
                    revenue = amt
                elif acc == "당기순이익" and net_income is None:
                    net_income = amt
            if revenue is not None or net_income is not None:
                break
    if revenue and net_income is not None:
        net_margin = round(net_income / revenue * 100, 1)

    return {
        "name": name, "corp_code": corp_code,
        "price": price, "shares": shares, "market_cap": market_cap,
        "eps": eps, "per": per, "revenue": revenue, "net_income": net_income,
        "net_margin": net_margin,
    }


def _company_entity_id(conn, stock_code: str) -> int | None:
    r = conn.execute("SELECT id FROM entities WHERE type='company' AND aliases=? LIMIT 1",
                     (stock_code,)).fetchone()
    return r["id"] if r else None


def _evidence(conn, name: str, event: str) -> list[dict]:
    """근거 문서 발췌 — search(종목명 이벤트) top 문서."""
    from pipeline.search import search
    from pipeline.visibility import get_muted, is_muted
    hits = search(f"{name or ''} {event}".strip(), k=TOP_DOCS + 5)
    muted = get_muted(conn)
    docs = []
    for h in hits:
        d = conn.execute(f"""
            SELECT id, source_type, source_id, title, url, published_at,
                   substr(markdown, 1, {EXCERPT}) excerpt
            FROM raw_documents WHERE id=?""", (h["doc_id"],)).fetchone()
        if d and not is_muted(d["source_type"], d["source_id"] or "", d["url"], muted):
            docs.append(dict(d))
        if len(docs) >= TOP_DOCS:
            break
    return docs


def _fmt(v, unit=""):
    return f"{v}{unit}" if v is not None else "미상"


def _build_prompt(name: str, event: str, a: dict, docs: list[dict]) -> str:
    ctx = "\n\n".join(
        f"[{i+1}] ({d['source_type']}, {(d['published_at'] or '')[:10]}) {d['title']}\n{d['excerpt']}"
        for i, d in enumerate(docs)) or "(관련 수집 문서 없음)"
    anchor = (
        f"- 현재가: {_fmt(a['price'], '원')}\n"
        f"- EPS: {_fmt(a['eps'])}\n"
        f"- PER: {_fmt(a['per'], '배')}\n"
        f"- 최근 연간 매출액: {_fmt(a['revenue'], '원')}\n"
        f"- 최근 연간 당기순이익: {_fmt(a['net_income'], '원')}\n"
        f"- 순이익률: {_fmt(a['net_margin'], '%')}\n"
        f"- 주식수: {_fmt(a['shares'])}"
    )
    return (
        "너는 투자 리서치 애널리스트다. 아래 [종목]과 [이벤트]에 대해 조건부 업사이드/하방을 모델링해 "
        "결과를 JSON으로 정리한다. (설명·머리말 없이 JSON만, 코드블록 없이.)\n"
        f"[종목] {name or '(미상)'}\n[이벤트] {event}\n"
        f"[앵커 — 결정적 데이터]\n{anchor}\n\n"
        "방법(정확도 순):\n"
        "1. 매출 수혜: 이벤트가 이 기업 매출에 주는 영향 (P×Q · Capa×가동률 · TAM×점유율 중 성격에 맞게).\n"
        "2. 이익 add: 매출 증분에 러프 이익률 적용.\n"
        "3. EPS 업데이트 → 새 적정주가: 갱신 EPS × 타당 멀티플.\n"
        "4. 먼 미래·추론 시기상조면 실적 대신 기대감을 멀티플에 반영 (method='멀티플 리레이팅', 현재 PER→목표 PER).\n\n"
        'JSON만 출력 (다른 텍스트·펜스 금지):\n'
        '{"method":"P×Q|Capa×가동률|TAM×점유율|멀티플 리레이팅",'
        '"scenarios":[{"name":"보수","prob":0.0,"assumptions":["가정1","가정2"],'
        '"revenue_delta_pct":null,"margin":null,"eps_new":null,"multiple":null,'
        '"fair_price":0,"upside_pct":0},'
        '{"name":"기본",...},{"name":"낙관",...}],'
        '"downside":{"floor_price":null,"downside_pct":null,"basis":"펀더멘탈 지지선 근거"},'
        '"invalidation":["이 조건 깨지면 논리 무효1","..."],"summary":"한 줄 요약"}\n\n'
        "규칙:\n"
        "- scenarios는 반드시 보수/기본/낙관 3개. prob는 0~1 (셋 합 ~1).\n"
        "- **모든 수치 가정은 assumptions[]에 전부 명시.** 근거 없는 수치는 문장 끝에 '(가정)' 표기.\n"
        "- 매출 수혜→이익→EPS→적정주가로 전개 (method 1~3). 먼 미래·불확실이면 method='멀티플 리레이팅'.\n"
        "- upside_pct = (fair_price - 현재가) / 현재가 * 100. 현재가 미상이면 upside_pct=null.\n"
        "- point target 금지 — 범위+조건부. 과장 금지, 정직한 범위.\n"
        "- downside: 실적/자산가치 기반 하방 지지선. invalidation: 관측 가능한 무효화 조건.\n"
        f"\n[수집 문서]\n{ctx}"
    )


def _call_opus(prompt: str) -> dict:
    """opus 호출 + 견고화 (펜스 제거·2회 재시도). 실패 시 RuntimeError."""
    data, last_err = None, ""
    for _ in range(2):
        proc = subprocess.run(
            [_claude_bin(), "-p", "--model", UPSIDE_MODEL, "--output-format", "json", prompt],
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            last_err = f"rc={proc.returncode} out={proc.stdout.strip()[:150]!r} err={proc.stderr.strip()[:120]!r}"
            continue
        try:
            raw = json.loads(proc.stdout).get("result", "")
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            s, e = raw.find("{"), raw.rfind("}")
            if s < 0 or e <= s:
                last_err = f"JSON 없음: {raw[:80]!r}"
                continue
            data = json.loads(raw[s:e + 1])
            break
        except Exception as ex:  # noqa: BLE001 — 절단·형식 오류 모두 재시도
            last_err = f"{type(ex).__name__}: {str(ex)[:100]}"
    if data is None:
        raise RuntimeError(f"upside 파싱 실패(2회): {last_err}")
    return data


def build_upside_model(conn, stock_code: str, event: str, force: bool = False) -> dict:
    """이벤트 → 종목 조건부 업사이드/하방 모델. models 테이블 캐시·적재.
    반환: status ok|error|unavailable. force가 아니면 저장분을 그대로 반환(opus 재실행 없음)."""
    try:
        a = _anchor(conn, stock_code)
        name = a["name"] or stock_code
        model_name = f"{name} · {event} 업사이드"

        # 캐시: 이미 만든 모델이 있으면 opus 없이 즉시 반환 (매번 재생성 방지)
        if not force:
            row = conn.execute(
                "SELECT spec_json, updated_at FROM models WHERE name=?", (model_name,)).fetchone()
            if row and row["spec_json"]:
                spec = json.loads(row["spec_json"])
                return {"status": "ok", "stock": name, "stock_code": stock_code,
                        "cached": True, "updated_at": row["updated_at"], **spec}

        if llm_engine() != "claude-code":
            return {"status": "unavailable"}
        docs = _evidence(conn, a["name"], event)
        data = _call_opus(_build_prompt(a["name"], event, a, docs))

        anchor = {"price": a["price"], "eps": a["eps"], "per": a["per"],
                  "revenue": a["revenue"], "net_margin": a["net_margin"]}
        result = {
            "status": "ok", "stock": name, "stock_code": stock_code, "anchor": anchor,
            "method": data.get("method"),
            "scenarios": data.get("scenarios", []),
            "downside": data.get("downside"),
            "invalidation": data.get("invalidation", []),
            "summary": data.get("summary"),
        }

        # models 적재 (name UNIQUE upsert) — spec_json에 앵커 포함
        entity_id = _company_entity_id(conn, stock_code)
        spec = {k: result[k] for k in ("anchor", "method", "scenarios", "downside",
                                       "invalidation", "summary")}
        conn.execute("""
            INSERT INTO models (name, spec_json, output_entity_id, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(name) DO UPDATE SET
                spec_json=excluded.spec_json,
                output_entity_id=excluded.output_entity_id,
                updated_at=datetime('now')""",
            (model_name, json.dumps(spec, ensure_ascii=False), entity_id))
        conn.commit()
        result["cached"] = False
        return result
    except Exception as e:  # noqa: BLE001 — opus 드리프트·타임아웃 포함, 상위에서 error 처리
        print(f"[upside_model] 실패: {type(e).__name__}: {e}")
        return {"status": "error"}
