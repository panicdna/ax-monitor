"""요약 LLM 호출 — ahn-vatar `backend/llm.py` 와 동등(stdlib urllib 사용).

OpenAI 호환 chat completions API 로 컨텍스트 묶음을 요약한다. `LLM_BASE_URL` 미설정 시
결정적 stub 으로 폴백해 LLM 없이도 요약 경로의 e2e 흐름을 검증할 수 있다.

env:
  LLM_BASE_URL        예) http://10.116.67.153:1234/v1 (비우면 stub)
  LLM_MODEL           예) google/gemma-4-e4b
  LLM_API_KEY         Bearer 토큰 (있으면)
  LLM_RESPONSE_FORMAT json_schema(기본) | json_object | text
  LLM_MAX_TOKENS      기본 2800
  LLM_TIMEOUT_S       기본 30
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any


def _env_int(name: str, default: int) -> int:
    """env 가 비정수여도 기본값으로 안전 폴백 (요약 실패 방지)."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


SYSTEM_PROMPT = (
    "당신은 개발자 세션을 분석해 '이 사람이 실제로 무슨 일을 했는지' 를 구체적으로 "
    "기록하는 분석가입니다. 입력은 (cwd, user_turns, tool_calls, skills, sub_agents, "
    "assistant_outline, outcome_hint) 컨텍스트 묶음입니다. 한국어로 구체적으로 작성하세요. "
    "파일 경로·코드 원문·사번·이메일·IP 등 식별·원문 정보 출력 금지."
)

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "maxLength": 200},
        "outcome": {"type": "string", "maxLength": 200},
        "task_category": {"type": "string", "maxLength": 32},
        "activities": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "domain_keywords": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
        "artifacts_touched": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {"kind": {"type": "string"}, "count": {"type": "number"}},
                "required": ["kind", "count"],
            },
        },
        "difficulty_signal": {"type": "string"},
        "reusable_pattern": {"type": "string", "maxLength": 200},
    },
    "required": [
        "intent",
        "outcome",
        "task_category",
        "activities",
        "domain_keywords",
        "artifacts_touched",
        "difficulty_signal",
        "reusable_pattern",
    ],
}


def _response_format(fmt: str) -> dict:
    if fmt == "json_object":
        return {"type": "json_object"}
    if fmt == "text":
        return {"type": "text"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "session_summary",
            "strict": True,
            "schema": SUMMARY_SCHEMA,
        },
    }


def summarize(ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """컨텍스트 묶음 → (요약 JSON, 처리정보). 실패/미설정 시 stub 폴백."""
    base_url = (os.getenv("LLM_BASE_URL") or "").rstrip("/")
    if not base_url:
        return _stub_summary(ctx), {
            "mode": "stub-noconfig",
            "model": "",
            "ms": 0,
            "ok": False,
            "error": "LLM_BASE_URL unset",
        }

    model = os.getenv("LLM_MODEL", "google/gemma-4-e4b")
    t0 = time.monotonic()
    try:
        out = _call_llm(ctx, base_url, model)
        ms = int((time.monotonic() - t0) * 1000)
        return out, {"mode": "llm", "model": model, "ms": ms, "ok": True, "error": ""}
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 stub 으로 흐름 보존
        ms = int((time.monotonic() - t0) * 1000)
        return _stub_summary(ctx), {
            "mode": "stub-error",
            "model": model,
            "ms": ms,
            "ok": False,
            "error": str(e),
        }


def _call_llm(ctx: dict[str, Any], base_url: str, model: str) -> dict[str, Any]:
    url = f"{base_url}/chat/completions"
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": _env_int("LLM_MAX_TOKENS", 2800),
        "response_format": _response_format(
            os.getenv("LLM_RESPONSE_FORMAT", "json_schema")
        ),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)},
        ],
    }
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("LLM_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    timeout = _env_float("LLM_TIMEOUT_S", 30.0)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — 신뢰된 사내 URL
        payload = json.loads(resp.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    # response_format=text 는 JSON 이 아니라 평문 → json.loads 하면 항상 실패해
    # stub 으로 떨어진다. text 일 땐 본문을 intent 로 매핑하고 나머지는 빈값.
    if os.getenv("LLM_RESPONSE_FORMAT", "json_schema") == "text":
        return {
            "intent": (content or "").strip()[:200],
            "outcome": "",
            "task_category": "uncategorized",
            "activities": [],
            "domain_keywords": [],
            "artifacts_touched": [],
            "difficulty_signal": "",
            "reusable_pattern": "",
        }
    return json.loads(content)


def _stub_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    """LLM 미설정/실패 시 폴백 — 컨텍스트에서 결정적으로 끄집어낸 최소 요약."""
    user_turns = ctx.get("user_turns") or []
    intent = (user_turns[0][:120] if user_turns else "") or "(no user turn)"
    skills = ctx.get("skills") or []
    tools = [tc.get("name") for tc in (ctx.get("tool_calls") or []) if tc.get("name")]
    keywords = list(dict.fromkeys(list(skills) + list(tools)))[:6]
    activities = [
        f"{tc.get('name')} {tc.get('dir') or tc.get('bash') or ''}".strip()
        for tc in (ctx.get("tool_calls") or [])[:6]
        if tc.get("name")
    ]
    return {
        "intent": intent,
        "outcome": ctx.get("outcome_hint") or "",
        "task_category": "uncategorized",
        "activities": activities,
        "domain_keywords": keywords,
        "artifacts_touched": [],
        "difficulty_signal": "",
        "reusable_pattern": "",
    }
