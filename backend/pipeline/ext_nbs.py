"""중국 국가통계국(NBS) 월간 공업 주요 제품 생산량 수집 (docs/specs/value-chain.md §7, LLM 0).

출처: NBS 신 데이터 플랫폼(data.stats.gov.cn/dg) 키 없는 JSON. 月度数据 → 工业 → 工业主要产品产量 아래 제품별 카탈로그.
  트리   GET  /new/queryIndexTreeAsync?pid=<부모>&code=1        → data[]: {_id, name, isLeaf}
  지표   GET  /new/queryIndicatorsByCid?cid=<카탈로그>           → data.list[]: {_id, dp, i_showname, du_name}
           dp '1' = 当期值(本期), '21' = 累计值(本期累计), '11'/'12' = 증감률(저장 안 함)
  값     POST /stream/esData                                    → data[]: {code:'YYYYMMMM', values[]: {_id, dp, value:'529.0'|''}}
카탈로그 ID는 신 플랫폼이라 바뀔 수 있어 이름으로 트리에서 찾고, 실패하면 알려진 ID로 대체한다(어느 경로인지 결과 path에 남김).
둘 다 안 되면 조용히 빈 값을 내지 않고 status=error.
1·2월: NBS는 1월 当期值를 비우고 2월은 1~2월 누계만 내는 해가 많다. 1월 当期值가 없고 2월 累计值가 있으면
  - 2월 当期值가 있으면 1월 = 2월 누계 − 2월(정확한 차),
  - 없으면 1월 = 2월 = 2월 누계 / 2 (근사 — source에 표기). 그 밖의 달은 비어 있으면 비운다.
단위는 API의 du_name(亿块·万台·万射频模块)을 그대로 저장한다.
"""
from __future__ import annotations

from datetime import date

import requests

from pipeline.ext_series import upsert

BASE = "https://data.stats.gov.cn/dg/website/publicrelease/web/external"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
           "Referer": "https://data.stats.gov.cn/"}
SOURCE = "NBS 工业主要产品产量 当期值"
SPLIT_NOTE = " (1·2월은 1~2월 누계를 반씩)"
START = "201801"
TREE_PATH = ["月度数据", "工业", "工业主要产品产量"]
# 시리즈 → 허용 카탈로그 이름들(트리 표기), 알려진 ID(대체 경로)
PRODUCTS = {
    "nbs:ic_output": (("集成电路",), "decec4300f1249e89e409a64ac403ad8"),
    "nbs:smartphone_output": (("智能手机",), "acd6258944b546bdb5e468f539908b7b"),
    "nbs:mobile_output": (("移动通信手持机（手机）", "移动通信手持机(手机)", "手机"), "63833243055942409a1cb4bcae6cf05b"),
    "nbs:pc_output": (("微型计算机设备",), "3577f56ebdc54f56a40933ded4217056"),
    "nbs:basestation_output": (("移动通信基站设备",), "7f789a482576451589d2d851260e5a91"),
}
KNOWN_ROOT = "fc982599aa684be7969d7b90b1bd0e84"  # 月度数据


def _get(path: str, **params) -> dict:
    res = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=30)
    res.raise_for_status()
    body = res.json()
    if not body.get("success"):
        raise ValueError(f"NBS 응답 실패 {path}: {body.get('message')}")
    return body["data"]


def find_child(items: list[dict], names) -> str | None:
    """트리 항목들에서 이름(공백 무시)이 일치하는 _id"""
    by_name = {(x.get("name") or "").strip(): x["_id"] for x in items}
    return next((by_name[n] for n in names if n in by_name), None)


def lookup_catalogs() -> tuple[str, dict[str, str]]:
    """트리를 이름으로 내려가 (rootId, {series: cid}). 경로 중간이 없으면 ValueError"""
    pid, root = "", None
    for name in TREE_PATH:
        nid = find_child(_get("/new/queryIndexTreeAsync", pid=pid, code=1), (name,))
        if nid is None:
            raise ValueError(f"트리에서 '{name}'을 찾지 못함")
        root, pid = root or nid, nid  # 첫 단계(月度数据)의 id가 rootId
    leaves = _get("/new/queryIndexTreeAsync", pid=pid, code=1)
    return root, {s: cid for s, (names, _) in PRODUCTS.items() if (cid := find_child(leaves, names))}


def pick_indicators(items: list[dict]) -> tuple[str, str | None, str]:
    """지표 목록 → (当期值 id, 累计值 id, 단위). 当期值가 없으면 ValueError"""
    cur = next((x for x in items if str(x.get("dp")) == "1" and "当期值" in (x.get("i_showname") or "")), None)
    if cur is None:
        raise ValueError(f"当期值 지표 없음: {[x.get('i_showname') for x in items]}")
    ytd = next((x for x in items if str(x.get("dp")) == "21" and "累计值" in (x.get("i_showname") or "")), None)
    return cur["_id"], ytd and ytd["_id"], (cur.get("du_name") or "").strip()


def parse_es(data: list[dict], cur_id: str, ytd_id: str | None) -> tuple[dict[str, float], dict[str, float]]:
    """esData data[] → ({YYYY-MM: 当期值}, {YYYY-MM: 累计值}). 빈 문자열은 결측"""
    cur, ytd = {}, {}
    for row in data:
        code = row.get("code") or ""
        if len(code) < 6 or not code[:6].isdigit():
            continue
        period = f"{code[:4]}-{code[4:6]}"
        for v in row.get("values") or []:
            val = str(v.get("value") or "").strip()
            if not val:
                continue
            if v.get("_id") == cur_id:
                cur[period] = float(val)
            elif ytd_id and v.get("_id") == ytd_id:
                ytd[period] = float(val)
    return cur, ytd


def fill_jan_feb(cur: dict[str, float], ytd: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """1·2월 결측 보정 → (보정된 当期值, 반분한 달 목록). 2월 누계가 있는 해만 손댄다"""
    out, split = dict(cur), []
    for feb, total in ytd.items():
        if not feb.endswith("-02"):
            continue
        jan = feb[:5] + "01"
        if jan in out and feb in out:
            continue
        if jan in out:
            out[feb] = total - out[jan]
        elif feb in out:
            out[jan] = total - out[feb]
        else:
            out[jan] = out[feb] = total / 2
            split += [jan, feb]
    return out, sorted(split)


def _fetch(cid: str, root: str) -> tuple[dict[str, float], list[str], str]:
    cur_id, ytd_id, unit = pick_indicators(_get("/new/queryIndicatorsByCid", cid=cid, dt="", name="")["list"])
    body = {"cid": cid, "indicatorIds": [i for i in (cur_id, ytd_id) if i], "daCatalogId": "",
            "das": [{"text": "全国", "value": "000000000000"}], "showType": "1",
            "dts": [f"{START}MM-{date.today().year}12MM"], "rootId": root}
    res = requests.post(f"{BASE}/stream/esData", json=body, headers=HEADERS, timeout=60)
    res.raise_for_status()
    payload = res.json()
    if not payload.get("success"):
        raise ValueError(f"esData 실패: {payload.get('message')}")
    cur, ytd = parse_es(payload["data"], cur_id, ytd_id)
    values, split = fill_jan_feb(cur, ytd)
    return {p: v for p, v in values.items() if p >= f"{START[:4]}-{START[4:]}"}, split, unit


def collect() -> dict:
    from database import get_connection
    try:
        root, cids = lookup_catalogs()
        path, lookup_err = "tree", None
    except Exception as e:  # noqa: BLE001 — 트리 실패는 알려진 ID로 대체하고 경로를 남긴다
        root, cids, path, lookup_err = KNOWN_ROOT, {}, "fallback_ids", str(e)
    if len(cids) < len(PRODUCTS):
        cids = {**{s: kid for s, (_, kid) in PRODUCTS.items()}, **cids}
        path = "tree+fallback_ids" if path == "tree" else path

    fetched, errors = {}, {}
    for s, cid in cids.items():
        try:
            fetched[s] = _fetch(cid, root)
            if not fetched[s][0]:
                raise ValueError("값이 하나도 없음")
        except Exception as e:  # noqa: BLE001
            fetched.pop(s, None)
            errors[s] = str(e)
    if not fetched:
        return {"stored": 0, "series": [], "latest": None, "status": "error", "path": path,
                "error": f"NBS 공업 제품 생산량 카테고리를 찾지 못함 — 트리 조회({lookup_err or '부분 성공'})와 "
                         f"알려진 ID 모두 실패: {errors}"}

    stored, info = 0, {}
    conn = get_connection()
    try:
        for s, (values, split, unit) in fetched.items():
            rows = sorted(values.items())
            stored += upsert(conn, s, rows, unit, SOURCE + (SPLIT_NOTE if split else ""))
            info[s] = {"unit": unit, "rows": len(rows), "first": rows[0][0], "latest": rows[-1][0], "split": split}
        conn.commit()
    finally:
        conn.close()
    missing = [s for s in PRODUCTS if s not in fetched]
    out = {"stored": stored, "series": list(fetched), "latest": max(i["latest"] for i in info.values()),
           "status": "partial" if missing else "ok", "path": path, "detail": info}
    if missing:
        out["error"] = f"일부 시리즈 실패: {errors}"
    return out
