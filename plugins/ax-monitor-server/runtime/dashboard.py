"""최소 대시보드 — captures/ 에 쌓인 수신 세션을 브라우저로 조회하는 frontend 조각.

retail 서버를 avatar-ax(backend+frontend+db) 자립형 1-프로세스 등가물로 만든다:
  - backend(수신)  : main.py 의 POST /v1/sessions
  - db(저장)       : captures/<session>.meta.json 파일 (별도 DB 없이 파일이 대신)
  - frontend(조회) : 이 모듈 — captures 의 메타 사이드카를 읽어 HTML/JSON 으로 제공

production 동등성·stdlib only·의존성 0 원칙 유지. 새 저장소를 도입하지 않고
이미 쌓이는 메타 사이드카를 읽기 전용 소스로 재사용한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _stem_of(meta_path: Path) -> str:
    """'<stem>.meta.json' → '<stem>'. Path.stem 은 '.json' 만 떼므로 직접 자른다."""
    name = meta_path.name
    return name[: -len(".meta.json")] if name.endswith(".meta.json") else meta_path.stem


def list_sessions(captures_dir: Path) -> list[dict[str, Any]]:
    """captures/*.meta.json → 대시보드용 요약 행(최신 수신순)."""
    rows: list[dict[str, Any]] = []
    if not captures_dir.exists():
        return rows
    for meta_path in captures_dir.glob("*.meta.json"):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue  # 깨진/기록 중 파일은 건너뛴다 (서버 견고성과 동일 기조)
        headers = data.get("headers") or {}
        meta = data.get("meta") or {}
        summary = data.get("summary") or {}
        llm = data.get("llm") or {}
        rows.append(
            {
                "stem": _stem_of(meta_path),
                "session_id": headers.get("X-Session-Id") or _stem_of(meta_path),
                "user": headers.get("X-User-Id") or "",
                "cwd": headers.get("X-Cwd") or "",
                "received_at": data.get("received_at") or "",
                "bytes": data.get("received_bytes") or 0,
                "turns": meta.get("turns") or 0,
                "tokens": meta.get("tokens") or 0,
                "tools": meta.get("tools_used") or [],
                "skills": [s.get("name") for s in (meta.get("skills_used") or [])],
                "sub_agents": [a.get("name") for a in (meta.get("sub_agents_used") or [])],
                "intent": summary.get("intent") or "",
                "category": summary.get("task_category") or "",
                "llm_mode": llm.get("mode") or "",
            }
        )
    rows.sort(key=lambda r: r["received_at"], reverse=True)
    return rows


def session_detail(captures_dir: Path, stem: str) -> dict[str, Any] | None:
    """단일 세션의 메타 사이드카 전체(raw_breakdown·meta·summary·context_bundle)."""
    # stem 은 파일명에서 온 안전 문자열이지만, 경로 탈출 방어로 basename 만 허용.
    if "/" in stem or "\\" in stem or ".." in stem:
        return None
    path = captures_dir / f"{stem}.meta.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── 자립형 대시보드 HTML (외부 CDN/빌드 없이 인라인) ─────────────────
DASHBOARD_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>retail 서버 · 수신 대시보드</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
         background: #0e1116; color: #d7dde5; }
  header { padding: 14px 20px; border-bottom: 1px solid #222a35;
           display: flex; align-items: baseline; gap: 16px; position: sticky; top: 0;
           background: #0e1116; }
  header h1 { font-size: 15px; margin: 0; color: #7ee787; }
  header .muted { color: #768390; font-size: 12px; }
  header .spacer { flex: 1; }
  button { background: #21262d; color: #d7dde5; border: 1px solid #30363d;
           border-radius: 6px; padding: 4px 10px; cursor: pointer; font: inherit; }
  button:hover { background: #30363d; }
  main { display: grid; grid-template-columns: 1fr 1fr; gap: 0; height: calc(100vh - 51px); }
  .list { overflow: auto; border-right: 1px solid #222a35; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 7px 12px; border-bottom: 1px solid #1b212b;
           white-space: nowrap; }
  th { position: sticky; top: 0; background: #161b22; color: #768390; font-weight: 600;
       font-size: 12px; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: #161b22; }
  tbody tr.sel { background: #1f2630; }
  td.num { text-align: right; color: #9fb1c1; }
  .pill { display: inline-block; background: #1f2630; border: 1px solid #30363d;
          border-radius: 10px; padding: 0 7px; margin: 1px 2px; font-size: 11px; color: #adbac7; }
  .intent { color: #768390; max-width: 280px; overflow: hidden; text-overflow: ellipsis; }
  .detail { overflow: auto; padding: 16px 20px; }
  .detail h2 { font-size: 13px; color: #7ee787; margin: 18px 0 6px; }
  .detail .kv { color: #768390; }
  pre { background: #161b22; border: 1px solid #222a35; border-radius: 6px;
        padding: 12px; overflow: auto; font-size: 12.5px; white-space: pre-wrap;
        word-break: break-word; }
  .empty { color: #768390; padding: 40px; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>retail 서버</h1>
  <span class="muted">hook 수신 대시보드 · captures/</span>
  <span class="spacer"></span>
  <span class="muted" id="count">—</span>
  <label class="muted"><input type="checkbox" id="auto" checked /> 자동새로고침(5s)</label>
  <button onclick="load()">새로고침</button>
</header>
<main>
  <div class="list">
    <table>
      <thead><tr>
        <th>수신시각</th><th>user</th><th>session</th>
        <th class="num">turns</th><th class="num">tokens</th><th>intent</th>
      </tr></thead>
      <tbody id="rows"><tr><td colspan="6" class="empty">불러오는 중…</td></tr></tbody>
    </table>
  </div>
  <div class="detail" id="detail"><div class="empty">왼쪽에서 세션을 선택하세요.</div></div>
</main>
<script>
let SESSIONS = [], selected = null;

async function load() {
  try {
    const r = await fetch('/api/sessions');
    const j = await r.json();
    SESSIONS = j.sessions || [];
  } catch (e) { SESSIONS = []; }
  render();
}

function esc(s) { return String(s == null ? '' : s); }

function render() {
  document.getElementById('count').textContent = SESSIONS.length + ' sessions';
  const tb = document.getElementById('rows');
  if (!SESSIONS.length) {
    tb.innerHTML = '<tr><td colspan="6" class="empty">아직 수신된 세션이 없습니다.</td></tr>';
    return;
  }
  tb.innerHTML = '';
  for (const s of SESSIONS) {
    const tr = document.createElement('tr');
    if (s.stem === selected) tr.className = 'sel';
    const when = (s.received_at || '').replace('T', ' ').replace('+00:00', '');
    tr.innerHTML =
      '<td>' + esc(when) + '</td>' +
      '<td>' + esc(s.user) + '</td>' +
      '<td>' + esc(s.session_id) + '</td>' +
      '<td class="num">' + esc(s.turns) + '</td>' +
      '<td class="num">' + Number(s.tokens || 0).toLocaleString() + '</td>' +
      '<td class="intent" title="' + esc(s.intent) + '">' + esc(s.intent) + '</td>';
    tr.onclick = () => showDetail(s.stem);
    tb.appendChild(tr);
  }
}

async function showDetail(stem) {
  selected = stem; render();
  const d = document.getElementById('detail');
  d.innerHTML = '<div class="empty">불러오는 중…</div>';
  let data;
  try { data = await (await fetch('/api/sessions/' + encodeURIComponent(stem))).json(); }
  catch (e) { d.innerHTML = '<div class="empty">상세를 불러오지 못했습니다.</div>'; return; }
  const h = data.headers || {}, m = data.meta || {}, b = data.raw_breakdown || {};
  const sm = data.summary || {}, llm = data.llm || {};
  const pills = (arr) => (arr || []).map(x =>
    '<span class="pill">' + esc(typeof x === 'object' ? (x.name + '×' + x.count) : x) + '</span>').join('');
  d.innerHTML =
    '<div class="kv">session <b>' + esc(h['X-Session-Id']) + '</b> · user ' + esc(h['X-User-Id']) +
      ' · ' + esc(data.received_at) + '</div>' +
    '<div class="kv">cwd ' + esc(h['X-Cwd']) + ' · ' + esc(data.received_bytes) + ' bytes / ' +
      esc(data.transcript_lines) + ' lines</div>' +
    '<h2>분해 (raw_breakdown)</h2>' +
    '<div>발화 ' + esc(b.user_messages) + ' · 응답 ' + esc(b.assistant_messages) +
      ' · tool_use ' + esc(b.tool_use) + ' · tool_result ' + esc(b.tool_result) +
      ' · skill ' + esc(b.skill_calls) + ' · agent ' + esc(b.agent_calls) + '</div>' +
    '<h2>메타</h2>' +
    '<div>turns ' + esc(m.turns) + ' · tokens ' + Number(m.tokens || 0).toLocaleString() + '</div>' +
    '<div>tools ' + pills(m.tools_used) + '</div>' +
    '<div>skills ' + pills(m.skills_used) + '</div>' +
    '<div>sub_agents ' + pills(m.sub_agents_used) + '</div>' +
    '<h2>요약 ' + (llm.mode ? '<span class="kv">(' + esc(llm.mode) +
      (llm.model ? ' · ' + esc(llm.model) : '') + ')</span>' : '') + '</h2>' +
    '<div>intent: ' + esc(sm.intent) + '</div>' +
    '<div>category: ' + esc(sm.task_category) + '</div>' +
    '<div>activities: ' + pills(sm.activities) + '</div>' +
    '<h2>원본 메타 (JSON)</h2>' +
    '<pre>' + esc(JSON.stringify(data, null, 2)) + '</pre>';
}

document.getElementById('auto').onchange = tick;
function tick() {
  if (window._t) clearInterval(window._t);
  if (document.getElementById('auto').checked) window._t = setInterval(load, 5000);
}
load(); tick();
</script>
</body>
</html>
"""
