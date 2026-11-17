"""Task-owned LLM configuration. Feature code supplies inputs, never provider options.

Existing environment names are resolved here. LLM_TASK_<TASK>_<FIELD> overrides
one task without affecting other tasks sharing its old environment variable.
"""
from dataclasses import dataclass
from types import MappingProxyType
import os
import re


@dataclass(frozen=True)
class ModelTarget:
    engine: str
    model: str
    effort: str | None = None


@dataclass(frozen=True)
class TaskSpec:
    model: str
    timeout: int = 180
    effort: str | None = None
    tools: tuple[str, ...] = ()
    model_env: str | None = None
    effort_env: str | None = None
    stream: bool = False
    schema: bool = False
    api_max_tokens: int = 4096


@dataclass(frozen=True)
class TaskPolicy:
    task: str
    primary: ModelTarget
    fallback: ModelTarget | None
    timeout: int
    tools: tuple[str, ...] = ()
    stream: bool = False
    schema: bool = False
    api_max_tokens: int = 4096


# Web tasks whose Codex fallback may use Codex web search (and nothing else); see llm._run_codex.
WEB_FALLBACK_TASKS = frozenset({'company.profile', 'chain.analyze', 'study.web'})

# Only configuration lives here; prompts, SQL and domain validation stay in features.
TASKS = MappingProxyType({
    "backfill.change_summary": TaskSpec("haiku", timeout=120),
    "backfill.geo_scope": TaskSpec("haiku", timeout=180),
    "experiment.explicit": TaskSpec("sonnet", timeout=300, stream=True),
    'actions.summarize': TaskSpec('haiku', timeout=180),
    'briefing.macro': TaskSpec('sonnet', timeout=300),
    'briefing.synthesize': TaskSpec('sonnet', timeout=300),
    'canon.extract': TaskSpec('opus', timeout=600, model_env='CANON_MODEL'),
    'chain.analyze': TaskSpec('opus', timeout=1200, tools=('WebSearch', 'WebFetch')),
    'chain.note': TaskSpec('sonnet', timeout=300),
    'chain.write': TaskSpec('sonnet', timeout=900),
    'chat.answer': TaskSpec('sonnet', timeout=300, model_env='RAG_MODEL', effort_env='CHAT_SYNTH_EFFORT', stream=True),
    'chat.note': TaskSpec('haiku', timeout=120, effort='low', model_env='CHAT_NOTE_MODEL'),
    'chat.review': TaskSpec('haiku', timeout=120, effort='low', model_env='CHAT_ROUTER_MODEL'),
    'chat.route': TaskSpec('haiku', timeout=120, effort='low', model_env='CHAT_ROUTER_MODEL'),
    'company.aliases': TaskSpec('haiku', timeout=180),
    'company.brief': TaskSpec('opus', timeout=300, model_env='BRIEF_MODEL'),
    'company.lens': TaskSpec('sonnet', timeout=300, model_env='LENS_MODEL'),
    'company.profile': TaskSpec('sonnet', timeout=180, tools=('WebSearch', 'WebFetch')),
    'company.upside': TaskSpec('opus', timeout=300, model_env='UPSIDE_MODEL'),
    'corporate_action.extract': TaskSpec('haiku', timeout=180),
    'digest.generate': TaskSpec('haiku', timeout=180, effort='low'),
    'document.causal': TaskSpec('sonnet', timeout=300, effort='low', model_env='DOC_CAUSAL_MODEL'),
    'document.claims': TaskSpec('haiku', timeout=180),
    'document.tag': TaskSpec('haiku', timeout=180, effort='low', api_max_tokens=1024),
    'document.tag_batch': TaskSpec('sonnet', timeout=420, effort='low'),
    'document.time_classify': TaskSpec('haiku', timeout=180, effort='low', api_max_tokens=1024),
    'earnings.expectation': TaskSpec('sonnet', timeout=300),
    'earnings.themes': TaskSpec('sonnet', timeout=300),
    'era.commentary': TaskSpec('sonnet', timeout=300, model_env='ERA_COMMENTARY_MODEL'),
    'expectations.extract': TaskSpec('haiku', timeout=180, schema=True),
    'image.calendar': TaskSpec('haiku', timeout=180, effort='low', tools=('Read',)),
    'image.read': TaskSpec('haiku', timeout=180, effort='low', tools=('Read',)),
    'knowledge.causal_review': TaskSpec('opus', timeout=400, model_env='KNOWLEDGE_MODEL'),
    'knowledge.check_falsifier': TaskSpec('opus', timeout=400, model_env='KNOWLEDGE_MODEL'),
    'knowledge.contradiction': TaskSpec('opus', timeout=400, model_env='KNOWLEDGE_MODEL'),
    'knowledge.classify': TaskSpec('haiku', timeout=180),
    'knowledge.falsifiers': TaskSpec('opus', timeout=400),
    'knowledge.promote': TaskSpec('opus', timeout=400, model_env='KNOWLEDGE_MODEL'),
    'knowledge.refutes': TaskSpec('opus', timeout=400, model_env='KNOWLEDGE_MODEL'),
    'macro.interpret': TaskSpec('sonnet', timeout=180),
    'market.today': TaskSpec('sonnet', timeout=300),
    'narrative.diff': TaskSpec('haiku', timeout=400),
    'narrative.generate': TaskSpec('opus', timeout=400, model_env='NARRATIVE_MODEL'),
    'narrative.mega': TaskSpec('opus', timeout=400, model_env='NARRATIVE_MODEL'),
    'narrative.mer': TaskSpec('opus', timeout=400, model_env='NARRATIVE_MODEL'),
    'narrative.reverify': TaskSpec('haiku', timeout=180, schema=True),
    'narrative.weekly': TaskSpec('sonnet', timeout=300),
    'ops.probe': TaskSpec('haiku', timeout=90, effort='low'),
    'preliminary.extract': TaskSpec('haiku', timeout=120, schema=True),
    'segments.extract': TaskSpec('haiku', timeout=120, schema=True),
    'pricing.extract': TaskSpec('sonnet', timeout=240, effort='low', model_env='PRICING_MODEL'),
    'proxy.extract': TaskSpec('haiku', timeout=180),
    'proxy.sentiment': TaskSpec('haiku', timeout=120),
    'proxy.suggest': TaskSpec('sonnet', timeout=240),
    'question.decompose': TaskSpec('sonnet', timeout=240),
    'question.derive': TaskSpec('sonnet', timeout=180),
    'question.from_insight': TaskSpec('haiku', timeout=60),
    'question.report': TaskSpec('sonnet', timeout=240),
    'question.summarize': TaskSpec('haiku', timeout=120),
    'report.analyze': TaskSpec('sonnet', timeout=240),
    'report.lead': TaskSpec('opus', timeout=360),
    'report.research': TaskSpec('sonnet', timeout=240),
    'report.write': TaskSpec('sonnet', timeout=420),
    'scenario.generate': TaskSpec('opus', timeout=300, model_env='SCENARIO_MODEL'),
    'sector.overview': TaskSpec('sonnet', timeout=180, schema=True),
    # Principle sentence -> numeric rules preview (the single-path candidate's engine-neutral path for
    # portfolio_principles.parse; the legacy route calls the Claude CLI directly).
    'portfolio.principle_parse': TaskSpec('haiku', timeout=60, schema=True),
    # Search-question refinement and the chart request's company-name assist (single-path candidate paths for
    # market_analysis.model.structured_call, which calls the Claude CLI directly in the legacy routes).
    'analysis.refine': TaskSpec('sonnet', timeout=90, schema=True, model_env='MARKET_ANALYSIS_MODEL'),
    'chart.company_assist': TaskSpec('haiku', timeout=20, schema=True),
    'signal.interpret_price': TaskSpec('haiku', timeout=180),
    'signal.interpret_surge': TaskSpec('haiku', timeout=180),
    'study.intent_plan': TaskSpec('haiku', timeout=45, effort='low'),
    'study.plan': TaskSpec('haiku', timeout=45, effort='low'),
    'study.web': TaskSpec('haiku', timeout=100, effort='low', tools=('WebSearch', 'WebFetch')),
    'telegram.continuation': TaskSpec('haiku', timeout=180),
    'thesis.challenge': TaskSpec('haiku', timeout=120, model_env='DEVILS_MODEL'),
    'thesis.decompose': TaskSpec('sonnet', timeout=180),
    'thesis.filter': TaskSpec('haiku', timeout=120),
    'trade.beneficiaries': TaskSpec('sonnet', timeout=180),
    'transcript.digest': TaskSpec('sonnet', timeout=300),
    'transcript.momentum_extract': TaskSpec('haiku', timeout=180),
    'transcript.momentum_summary': TaskSpec('sonnet', timeout=180),
    'transcript.reaction': TaskSpec('sonnet', timeout=300),
    'vocab.judge': TaskSpec('sonnet', timeout=300),
    'worldview.generate': TaskSpec('opus', timeout=300, model_env='WORLDVIEW_MODEL'),
    'youtube.digest': TaskSpec('opus', timeout=400),
})

FIELDS = frozenset({"MODEL", "EFFORT", "TIMEOUT", "FALLBACK_MODEL", "FALLBACK_ENGINE"})


def env_prefix(task: str) -> str:
    return "LLM_TASK_" + re.sub(r"[^A-Z0-9]", "_", task.upper()) + "_"


def _setting(env, key, default):
    value = env.get(key, default) if key else default
    return value.strip() if isinstance(value, str) else value


def resolve(task: str, *, engine: str = "claude-code", environ=None) -> TaskPolicy:
    """Resolve an immutable policy snapshot for one call. No provider I/O."""
    if task not in TASKS:
        raise ValueError(f"등록되지 않은 LLM 작업: {task}")
    if engine not in {"claude-code", "api"}:
        raise ValueError(f"지원하지 않는 기본 LLM 엔진: {engine}")
    env = os.environ if environ is None else environ
    spec = TASKS[task]
    prefix = env_prefix(task)
    model = _setting(env, prefix + "MODEL", _setting(env, spec.model_env, spec.model))
    effort = _setting(env, prefix + "EFFORT", _setting(env, spec.effort_env, spec.effort)) or None
    if not model or any(c.isspace() for c in model):
        raise ValueError(f"{task}: 유효하지 않은 모델 설정")
    if effort not in {None, "low", "medium", "high", "max"}:
        raise ValueError(f"{task}: 지원하지 않는 추론 강도 {effort!r}")
    try:
        timeout = int(_setting(env, prefix + "TIMEOUT", spec.timeout))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{task}: timeout은 양의 정수여야 합니다") from exc
    if timeout <= 0:
        raise ValueError(f"{task}: timeout은 양의 정수여야 합니다")
    fallback_engine = _setting(env, prefix + "FALLBACK_ENGINE", _setting(env, "LLM_FALLBACK_ENGINE", "codex-exec"))
    if fallback_engine not in {"codex-exec", "none", ""}:
        raise ValueError(f"{task}: 지원하지 않는 대체 엔진 {fallback_engine!r}")
    fallback_model = _setting(env, prefix + "FALLBACK_MODEL", _setting(env, "CODEX_FALLBACK_MODEL", "gpt-6.1-sol"))
    if not fallback_model or any(c.isspace() for c in fallback_model):
        raise ValueError(f"{task}: 유효하지 않은 대체 모델 설정")
    # Claude native web evidence cannot be synthesized from Codex completion text; the web tasks below fall back
    # to Codex's own web search instead (user direction: Codex as the LLM backup), with its opened pages as evidence.
    fallback = None
    if engine == "claude-code" and fallback_engine == "codex-exec" and (
            not (set(spec.tools) - {"Read"}) or task in WEB_FALLBACK_TASKS):
        fallback = ModelTarget("codex-exec", fallback_model, effort)
    if engine == "api" and (spec.tools or spec.schema):
        raise ValueError(f"{task}: API 엔진은 이 작업의 도구/구조화 출력 계약을 지원하지 않습니다")
    return TaskPolicy(task, ModelTarget(engine, model, effort), fallback, timeout,
                      spec.tools, spec.stream, spec.schema, spec.api_max_tokens)


def requested_model(task: str) -> str:
    """Requested model for existing cache/signature fields; not actual provider attribution."""
    return resolve(task).primary.model


def validate_configuration(environ=None) -> None:
    env = os.environ if environ is None else environ
    allowed = {env_prefix(task) + field for task in TASKS for field in FIELDS}
    unknown = sorted(key for key in env if key.startswith("LLM_TASK_") and key not in allowed)
    if unknown:
        raise ValueError("알 수 없는 LLM 작업 설정: " + ", ".join(unknown))
    for task in TASKS:
        resolve(task, environ=env)
