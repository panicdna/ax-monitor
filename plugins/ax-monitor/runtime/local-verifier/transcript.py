"""Transcript 분해 — raw 수신 기록이 무엇을 담고 있는지 결정적으로 센다(LLM 불필요).

hook 은 transcript 를 통째로 보내고, 이 서버는 그걸 그대로 저장한다. 분해 수치는 "무엇이
들어왔나"를 확인하기 위한 결정적 카운트일 뿐 — 요약·LLM 은 다루지 않는다.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Iterable


def _as_dict(v: Any) -> dict:
    """tool_use block 의 input 이 dict 가 아닐 때(None/list/str) 안전 폴백.

    깨진 JSONL 로 input 이 비-dict 여도 .get() AttributeError 로 분해가 멈추지 않게 한다.
    """
    return v if isinstance(v, dict) else {}


# ── JSONL 파싱 ────────────────────────────────────────────────────
def parse_jsonl(payload: bytes) -> list[dict]:
    """JSONL bytes → list[dict]. 깨진/빈 라인은 건너뛴다."""
    try:
        text = payload.decode("utf-8", errors="replace")
    except Exception:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


# ── raw_breakdown — 무엇이 들어있나 ───────────────────────────────
def raw_breakdown(transcript: Iterable[dict]) -> dict:
    """raw transcript 에 무엇이 들어있나 — hook 이 통째로 보낸 내용의 분해."""
    user_msgs = assistant_msgs = tool_use = tool_result = skill = agent = 0
    for line in transcript:
        if not isinstance(line, dict):
            continue
        t = line.get("type")
        msg = line.get("message") or {}
        content = msg.get("content")
        if t == "user":
            if isinstance(content, str) and content.strip():
                user_msgs += 1
            elif isinstance(content, list):
                has_text = any(
                    isinstance(b, dict) and b.get("type") == "text" for b in content
                )
                tool_result += sum(
                    1
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "tool_result"
                )
                if has_text:
                    user_msgs += 1
        elif t == "assistant" and isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "text" for b in content):
                assistant_msgs += 1
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tool_use += 1
                    name = b.get("name")
                    if name == "Skill":
                        skill += 1
                    elif name == "Agent":
                        agent += 1
    return {
        "user_messages": user_msgs,
        "assistant_messages": assistant_msgs,
        "tool_use": tool_use,
        "tool_result": tool_result,
        "skill_calls": skill,
        "agent_calls": agent,
    }


# ── extract_meta — 결정적 메타(도구/스킬/에이전트/턴/토큰) ─────────
def extract_meta(transcript: Iterable[dict]) -> dict:
    tool_names: list[str] = []
    skill_counter: Counter = Counter()
    agent_counter: Counter = Counter()
    turns = 0
    tokens = 0

    for line in transcript:
        if not isinstance(line, dict):
            continue
        if line.get("type") != "assistant":
            continue
        msg = line.get("message") or {}
        usage = msg.get("usage") or {}
        tokens += int(usage.get("input_tokens") or 0)
        tokens += int(usage.get("output_tokens") or 0)
        tokens += int(usage.get("cache_creation_input_tokens") or 0)

        content = msg.get("content")
        blocks = (
            [b for b in content if isinstance(b, dict)]
            if isinstance(content, list)
            else []
        )
        for block in blocks:
            if block.get("type") != "tool_use":
                continue
            turns += 1
            name = block.get("name") or ""
            tool_names.append(name)
            inp = _as_dict(block.get("input"))
            if name == "Skill":
                skill_counter[str(inp.get("skill") or inp.get("name") or "")] += 1
            elif name == "Agent":
                agent_counter[str(inp.get("subagent_type") or "general-purpose")] += 1

    return {
        "tools_used": sorted(set(t for t in tool_names if t)),
        "skills_used": [
            {"name": n, "count": c} for n, c in skill_counter.most_common() if n
        ],
        "sub_agents_used": [
            {"name": n, "count": c} for n, c in agent_counter.most_common() if n
        ],
        "turns": turns,
        "tokens": tokens,
    }
