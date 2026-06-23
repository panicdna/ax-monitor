"""Transcript 분해/요약 로직 — ahn-vatar Summarizer 와 동등하게 유지.

이 모듈은 production `backend/summarizer/jq_meta.py` 의 `raw_breakdown`/`extract_meta`
와 `backend/summarizer/context_bundle.py` 의 `build_bundle` 규칙을 그대로 옮긴 것이다.
로컬 검증 서버가 보여 주는 분해 수치가 실제 서버가 볼 수치와 일치하도록 같은 검출 규칙을
쓴다(transcript 라인 type, content block tool_use/tool_result, Skill→input.skill,
Agent→input.subagent_type).
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Any, Iterable


def _as_dict(v: Any) -> dict:
    """tool_use block 의 input 이 dict 가 아닐 때(None/list/str 등) 안전 폴백.

    깨진 JSONL 로 input 이 비-dict 여도 .get() AttributeError 로 전체 분석이
    멈추지 않게 한다. 유효 입력의 결과는 동일 — production 동등성 유지.
    """
    return v if isinstance(v, dict) else {}


# ── JSONL 파싱 ────────────────────────────────────────────────────
def parse_jsonl(payload: bytes) -> list[dict]:
    """JSONL bytes → list[dict]. 깨진/빈 라인은 건너뛴다 (서버와 동일)."""
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


# ── raw_breakdown (production 동등) ───────────────────────────────
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


# ── extract_meta (production 동등) ────────────────────────────────
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


# ── build_bundle (production 핵심 동등, LLM 입력 묶음) ─────────────
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_SECRET_RES = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[AWS_KEY]"),
    (re.compile(r"\b[0-9]{8}\b"), "[EMP_ID]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
]
_CHARS_PER_TOK = 4
_USER_TURNS_TOK_CAP = int(os.getenv("SUMMARIZER_USER_TURNS_TOK_CAP", "2000"))
_OUTCOME_HINT_CHAR_CAP = int(os.getenv("SUMMARIZER_OUTCOME_HINT_CHAR_CAP", "200"))


def build_bundle(transcript: list[dict], cwd: str) -> dict[str, Any]:
    return {
        "cwd": cwd or "",
        "user_turns": _user_turns(transcript),
        "tool_calls": _tool_calls(transcript),
        "skills": _unique_names(transcript, "Skill", "skill"),
        "sub_agents": _unique_names(transcript, "Agent", "subagent_type"),
        "assistant_outline": _assistant_outline(transcript),
        "outcome_hint": _outcome_hint(transcript),
    }


def _flatten_user_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text") or ""))
        return "\n".join(p for p in parts if p)
    return ""


def _user_turns(transcript: list[dict]) -> list[str]:
    raw: list[str] = []
    for line in transcript:
        if line.get("type") != "user":
            continue
        text = _flatten_user_content((line.get("message") or {}).get("content"))
        if not text:
            continue
        text = _CODE_BLOCK_RE.sub("[CODE_BLOCK omitted]", text)
        for rx, repl in _SECRET_RES:
            text = rx.sub(repl, text)
        raw.append(text)
    return _cap_total_tokens(raw, _USER_TURNS_TOK_CAP)


def _cap_total_tokens(items: list[str], limit_tok: int) -> list[str]:
    if not items:
        return []
    limit_chars = limit_tok * _CHARS_PER_TOK
    total = sum(len(s) for s in items)
    if total <= limit_chars:
        return items
    kept = [items[0]]
    remaining = limit_chars - len(items[0])
    for s in reversed(items[1:]):
        if remaining - len(s) < 0:
            break
        kept.append(s)
        remaining -= len(s)
    if len(kept) < len(items):
        kept.append(f"[... {len(items) - len(kept)} middle turns dropped ...]")
    return kept


def _tool_calls(transcript: list[dict]) -> list[dict]:
    out: list[dict] = []
    for line in transcript:
        if line.get("type") != "assistant":
            continue
        for block in (line.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            inp = _as_dict(block.get("input"))
            entry: dict[str, Any] = {"name": block.get("name") or ""}
            file_path = (
                inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
            )
            if file_path:
                entry["dir"] = os.path.dirname(str(file_path)) or str(file_path)
            cmd = inp.get("command")
            if cmd:
                c = str(cmd).strip()
                entry["bash"] = c.split()[0] if c else ""
            out.append(entry)
    return out


def _unique_names(transcript: list[dict], tool_name: str, key: str) -> list[str]:
    seen: list[str] = []
    for line in transcript:
        if line.get("type") != "assistant":
            continue
        for block in (line.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != tool_name:
                continue
            v = _as_dict(block.get("input")).get(key)
            if v and v not in seen:
                seen.append(str(v))
    return seen


def _assistant_outline(transcript: list[dict], max_lines: int = 30) -> list[str]:
    out: list[str] = []
    for line in transcript:
        if line.get("type") != "assistant":
            continue
        parts = [
            str(b.get("text") or "")
            for b in ((line.get("message") or {}).get("content") or [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        if not parts:
            continue
        text = _CODE_BLOCK_RE.sub("", "\n".join(parts))
        first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        if first:
            out.append(first[:120])
    return out[:max_lines]


def _outcome_hint(transcript: list[dict]) -> str:
    last_text = ""
    for line in transcript:
        if line.get("type") != "assistant":
            continue
        parts = [
            str(b.get("text") or "")
            for b in ((line.get("message") or {}).get("content") or [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        if parts:
            last_text = "\n".join(parts)
    if not last_text:
        return ""
    last_text = _CODE_BLOCK_RE.sub("", last_text)
    lines = [ln.strip() for ln in last_text.splitlines() if ln.strip()]
    return " ".join(lines[:2])[:_OUTCOME_HINT_CHAR_CAP]
