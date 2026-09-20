"""AG-UI events and a small, server-authored A2UI v0.8 interpretation form."""
from __future__ import annotations

import uuid

from models.market_analysis import AnalysisSpec

FIELDS = {
    "window_scope": ("최근 기간에 포함할 범위", [("breakout", "넥라인 돌파일"), ("formation", "패턴 형성 전체")]),
    "include_same_day": ("돌파와 신고가가 같은 날인 경우", [("false", "그 이후 날짜만"), ("true", "같은 날 포함")]),
    "price_basis": ("이동평균선 이탈 기준", [("close", "종가"), ("low", "장중 저가")]),
}


def pending_form(fields: list[str], spec: dict, *, recovery: bool = False) -> dict:
    interrupt_id = uuid.uuid4().hex
    surface_id = f"analysis-{interrupt_id}"
    question = "중단된 분석을 같은 데이터와 조건으로 재개합니다." if recovery else "계산에 필요한 해석을 확인해 주세요."
    components = [{"id": "heading", "component": {"Text": {"text": {"literalString": question}}}}]
    children = ["heading"]
    contents = []
    for field in fields:
        label, options = FIELDS[field]
        component_id = f"field-{field}"
        value = spec[field]
        value = str(value).lower() if isinstance(value, bool) else value
        contents.append({"key": field, "valueString": value})
        contents.append({"key": f"{field}_label", "valueString": label})
        components.append({"id": component_id, "component": {"MultipleChoice": {
            "selections": {"path": f"/{field}"},
            "maxAllowedSelections": 1,
            "options": [{"value": value, "label": {"literalString": text}} for value, text in options],
        }}})
        children.append(component_id)
    components.extend([
        {"id": "submit-label", "component": {"Text": {"text": {"literalString": "분석 재개" if recovery else "이 조건으로 분석"}}}},
        {"id": "submit", "component": {"Button": {"child": "submit-label", "primary": True,
            "action": {"name": "resume_analysis", "context": [
                {"key": field, "value": {"path": f"/{field}"}} for field in fields]}}}},
        {"id": "root", "component": {"Column": {"children": {"explicitList": children + ["submit"]}}}},
    ])
    return {
        "id": interrupt_id, "question": question, "surfaceId": surface_id, "fields": fields,
        "a2ui": [
            {"surfaceUpdate": {"surfaceId": surface_id, "components": components}},
            {"dataModelUpdate": {"surfaceId": surface_id, "path": "/", "contents": contents}},
            {"beginRendering": {"surfaceId": surface_id, "root": "root", "catalogId": "explorer-analysis-v1"}},
        ],
    }


def validate_reply(pending: dict, payload: dict, spec: dict | None) -> dict | None:
    """Accept only this surface's action and the fields it actually requested."""
    if "userAction" in payload:
        if set(payload) != {"userAction"} or not isinstance(payload["userAction"], dict):
            raise ValueError("Invalid A2UI action")
        payload = payload["userAction"]
    if "context" in payload or "name" in payload:
        allowed = {"name", "context", "surfaceId", "sourceComponentId", "timestamp"}
        if set(payload) - allowed or payload.get("name") != "resume_analysis":
            raise ValueError("Invalid A2UI action")
        if payload.get("surfaceId", pending["surfaceId"]) != pending["surfaceId"]:
            raise ValueError("Action belongs to another surface")
        payload = payload.get("context", {})
    if not isinstance(payload, dict) or set(payload) != set(pending["fields"]):
        raise ValueError("확인 요청에 포함된 조건만 답할 수 있습니다.")
    if spec is None:
        if payload:
            raise ValueError("No conditions to update")
        return None
    updated = dict(spec)
    for field, value in payload.items():
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        values = {v for v, _ in FIELDS[field][1]}
        if field == "include_same_day" and isinstance(value, bool):
            value = str(value).lower()
        if not isinstance(value, str) or value not in values:
            raise ValueError("Invalid interpretation value")
        updated[field] = value == "true" if field == "include_same_day" else value
    return AnalysisSpec.model_validate(updated).model_dump(mode="json")


def event(kind: str, **payload) -> dict:
    # Validate against the installed protocol package rather than maintaining a
    # lookalike wire schema. Sequence IDs are added by the durable store.
    from ag_ui import core
    classes = {
        "RUN_STARTED": core.RunStartedEvent, "RUN_FINISHED": core.RunFinishedEvent,
        "RUN_ERROR": core.RunErrorEvent, "STEP_STARTED": core.StepStartedEvent,
        "STEP_FINISHED": core.StepFinishedEvent, "CUSTOM": core.CustomEvent,
        "TEXT_MESSAGE_START": core.TextMessageStartEvent,
        "TEXT_MESSAGE_CONTENT": core.TextMessageContentEvent,
        "TEXT_MESSAGE_END": core.TextMessageEndEvent,
    }
    return classes[kind](type=kind, **payload).model_dump(mode="json", by_alias=True, exclude_none=True)
