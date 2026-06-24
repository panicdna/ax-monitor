#!/usr/bin/env bash
# ax-monitor-server — retail 서버 상주 런처 (nohup 기반 start/stop/status/restart).
#
# hook(ax-monitor)이 보내는 raw 세션 기록을 받아 캡처·분해·(옵션)요약하는 풀 retail
# 서버(main.py)를 백그라운드 데몬으로 띄운다. systemd 없이 어디서나 동작하도록 nohup +
# PID 파일로 관리한다. 설치 시 ~/.claude/ax-monitor-server/ 로 복사된다.
#
# 설치: /install-ax-server (이 디렉터리를 ~/.claude/ax-monitor-server/ 로 복사하고
#       지정한 host/port 로 서버를 기동).
# 제거: /uninstall-ax-server
#
# 환경 변수(설치 시 install skill 이 채워 넣음; 직접 실행 시 덮어쓰기 가능):
#   AX_SERVER_HOST       바인드 IP (기본 0.0.0.0 = 모든 인터페이스 → 다른 PC 접근 가능)
#   AX_SERVER_PORT       수신 포트 (기본 14200)
#   AX_SERVER_SUMMARIZE  1 이면 --summarize (OpenAI 호환 요약; LLM_BASE_URL 없으면 stub)
#   AX_SERVER_FORWARD    값이 있으면 --forward <URL> (상위 서버로 raw 중계)
#   AX_SERVER_CAPTURES   캡처 저장 위치 (기본 <설치dir>/captures)
#   AX_SERVER_LOG        서버 stdout 로그 (기본 ~/.claude/ax-server.log)
#   AX_SERVER_PID        PID 파일 (기본 <설치dir>/ax-server.pid)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 설치 시 install skill 이 기록한 설정 파일(있으면). KEY=value 형식. 이걸 source 해두면
# start 와 동일한 host/port/로그를 stop/status/restart 에서도 env 프리픽스 없이 그대로 쓴다.
# (인라인 env 보다 파일이 우선 — 설정 변경은 이 파일을 고치고 restart.)
[ -f "$HERE/ax-server.env" ] && { set -a; . "$HERE/ax-server.env"; set +a; }

HOST="${AX_SERVER_HOST:-0.0.0.0}"
PORT="${AX_SERVER_PORT:-14200}"
CAPTURES="${AX_SERVER_CAPTURES:-$HERE/captures}"
LOG="${AX_SERVER_LOG:-$HOME/.claude/ax-server.log}"
PID_FILE="${AX_SERVER_PID:-$HERE/ax-server.pid}"

# python3 우선(이 환경엔 python 심볼릭 링크가 없을 수 있음).
PY="$(command -v python3 || command -v python || true)"

_running_pid() {
  # PID 파일이 살아있는 프로세스를 가리키면 그 PID 를, 아니면 빈 값을 출력.
  [ -f "$PID_FILE" ] || return 1
  local pid; pid="$(cat "$PID_FILE" 2>/dev/null)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && { echo "$pid"; return 0; }
  return 1
}

cmd_start() {
  if pid="$(_running_pid)"; then
    echo "이미 실행 중 (pid=$pid, port=$PORT). 재시작은 restart."
    return 0
  fi
  [ -n "$PY" ] || { echo "✗ python3 없음 — 설치 후 'apt install python3' 또는 PATH 확인"; return 1; }
  mkdir -p "$CAPTURES" "$(dirname "$LOG")" 2>/dev/null || true

  local args=(--host "$HOST" --port "$PORT" --captures-dir "$CAPTURES")
  [ "${AX_SERVER_SUMMARIZE:-0}" = "1" ] && args+=(--summarize)
  [ -n "${AX_SERVER_FORWARD:-}" ] && args+=(--forward "$AX_SERVER_FORWARD")

  echo "기동: $PY $HERE/main.py ${args[*]}"
  nohup "$PY" "$HERE/main.py" "${args[@]}" >>"$LOG" 2>&1 &
  local pid=$!
  echo "$pid" >"$PID_FILE"
  sleep 0.6
  if kill -0 "$pid" 2>/dev/null; then
    echo "✓ 기동됨 (pid=$pid). 로그: $LOG"
  else
    echo "✗ 기동 직후 종료됨 — 로그 확인: tail -20 $LOG"; return 1
  fi
}

cmd_stop() {
  if pid="$(_running_pid)"; then
    kill "$pid" 2>/dev/null
    sleep 0.4
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "✓ 종료됨 (pid=$pid)"
  else
    rm -f "$PID_FILE" 2>/dev/null || true
    echo "실행 중이 아님."
  fi
}

cmd_status() {
  if pid="$(_running_pid)"; then
    echo "● 실행 중  pid=$pid  host=$HOST  port=$PORT"
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS --noproxy '*' -m3 "http://localhost:$PORT/health" >/dev/null 2>&1; then
        echo "  /health → ok"
      else
        echo "  /health → 응답 없음(기동 중이거나 포트 불일치?)"
      fi
    fi
    echo "  로그: $LOG"
  else
    echo "○ 실행 중 아님 (pid 파일: $PID_FILE)"
    return 1
  fi
}

case "${1:-}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  cmd_status ;;
  *) echo "사용법: $(basename "$0") {start|stop|restart|status}"; exit 2 ;;
esac
