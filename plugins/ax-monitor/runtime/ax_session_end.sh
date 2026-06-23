#!/usr/bin/env bash
# ax-monitor — Claude Code SessionEnd/Stop hook.
#
# 세션이 끝날 때(SessionEnd) 또는 매 응답 종료마다(Stop) 그 세션의 transcript(JSONL)를
# 측정 서버로 raw 그대로 한 번 전송한다(파싱·LLM 없음 — 업로드만). 사용자는 평소처럼
# claude 만 쓰면 된다 — 전송은 동기지만 서버가 수신 즉시 응답하므로 체감 0이고,
# 실패/지연해도 세션 종료를 막지 않는다.
#
# 설치: /install-ax-monitor (이 스크립트를 ~/.claude/ax-monitor/ 로 복사하고
#       ~/.claude/settings.json 에 hook 으로 등록).
# 제거: /uninstall-ax-monitor
#
# 환경 변수:
#   AX_SUMMARIZER_URL  측정 서버 주소 (기본 http://localhost:14210/v1/sessions = 로컬 verifier)
#   AX_USER_ID         측정에 쓰일 사용자 ID (기본 whoami; 사내는 Knox 메일 권장)
#   AX_PER_TURN=1      발사마다 session_id 에 턴 구분자(-t001…)를 붙여 서버에서 명령마다 별도 행
#   AX_HOOK_LOG        호출 로그 경로 (기본 ~/.claude/ax-hook.log)
#   AX_HOOK_STATE      턴 카운터 저장 위치 (기본 ~/.claude/ax-hook-state)
#   AX_MEASUREMENT_OFF=1  이 셸/세션에서 측정 제외(opt-out)
set -uo pipefail

# ── 호출 로그 ────────────────────────────────────────────────────
AX_HOOK_LOG="${AX_HOOK_LOG:-$HOME/.claude/ax-hook.log}"
mkdir -p "$(dirname "$AX_HOOK_LOG")" 2>/dev/null || true
_axlog() { printf '%s [ax-hook] %s\n' "$(date '+%F %T')" "$*" >>"$AX_HOOK_LOG" 2>/dev/null || true; }

_axlog "invoked pid=$$ cwd=$(pwd)"

# 0) opt-out
[ "${AX_MEASUREMENT_OFF:-0}" = "1" ] && { _axlog "skip: opt-out (AX_MEASUREMENT_OFF=1)"; exit 0; }

# jq 의존(없으면 전송 못 함) — 조용히 죽지 말고 기록하고 넘어간다.
if ! command -v jq >/dev/null 2>&1; then
  _axlog "skip: 'jq' 미설치 → 전송 생략"
  exit 0
fi

SUMMARIZER_URL="${AX_SUMMARIZER_URL:-http://localhost:14210/v1/sessions}"

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# transcript 없으면 보낼 게 없음 — 기록하고 종료.
if [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
  _axlog "skip: transcript 없음 (session=${SESSION_ID:-?} path=${TRANSCRIPT:-none})"
  exit 0
fi
[ -n "$SESSION_ID" ] || SESSION_ID=$(basename "$TRANSCRIPT" .jsonl)

USER_ID="${AX_USER_ID:-$(whoami)}"
BYTES=$(wc -c <"$TRANSCRIPT" 2>/dev/null | tr -d ' ' || echo '?')

# 전송에 쓸 session_id. 기본은 실제 session_id 그대로(= 세션당 한 행, 매 턴 갱신).
# AX_PER_TURN=1 이면 턴 구분자(-t001…)를 붙여 매 발사를 서버의 별도 행으로 만든다.
SEND_SESSION_ID="$SESSION_ID"
if [ "${AX_PER_TURN:-0}" = "1" ]; then
  STATE_DIR="${AX_HOOK_STATE:-$HOME/.claude/ax-hook-state}"
  mkdir -p "$STATE_DIR" 2>/dev/null || true
  CF="$STATE_DIR/$(echo "$SESSION_ID" | tr -c 'A-Za-z0-9._-' '_').turn"
  N=$(($(cat "$CF" 2>/dev/null || echo 0) + 1))
  echo "$N" >"$CF" 2>/dev/null || true
  SEND_SESSION_ID="${SESSION_ID}-t$(printf '%03d' "$N")"
fi

_axlog "send session=$SEND_SESSION_ID user=$USER_ID bytes=$BYTES url=$SUMMARIZER_URL"

# 동기 전송 + http_code 캡처. 실패/지연해도 세션 종료를 막지 않도록 --max-time.
# -f 를 빼서 4xx/5xx 도 코드로 기록(예: 413/500). --noproxy: 사내 proxy 환경에서 localhost 직접.
HTTP=$(curl -sS --noproxy "*" -o /dev/null -w '%{http_code}' -X POST "$SUMMARIZER_URL" \
  -H "Content-Type: application/x-ndjson" \
  -H "X-User-Id: $USER_ID" \
  -H "X-Session-Id: $SEND_SESSION_ID" \
  -H "X-Cwd: $CWD" \
  --data-binary @"$TRANSCRIPT" --max-time 10 2>>"$AX_HOOK_LOG")
CURL_EXIT=$?
_axlog "result session=$SEND_SESSION_ID http=${HTTP:-000} curl_exit=$CURL_EXIT"

exit 0
