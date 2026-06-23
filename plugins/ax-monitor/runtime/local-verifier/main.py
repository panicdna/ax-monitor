"""ax-monitor local verifier — hook 이 보내는 raw 기록을 그대로 받아 저장·확인하는 서버.

ax-monitor `SessionEnd`/`Stop` hook 의 전송 계약(`POST /v1/sessions`, X-User-Id/
X-Session-Id/X-Cwd, --data-binary raw JSONL)을 그대로 재현한다. 측정 서버 없이 단일 stdlib
http.server 로 떠서:

  1) raw body + 헤더를 captures/ 에 그대로 저장 (hook 이 무엇을 보냈나)
  2) 결정적 분해(발화/응답/tool_use/tool_result/skill/agent, tools·turns 등)를 리포트로 출력
  3) (--forward URL) 동일 raw POST 를 실제 백엔드로 중계

LLM/요약은 다루지 않는다 — hook 과 마찬가지로 raw 기록을 그대로 전달·보관만 한다.
응답은 실제 서버와 동일한 {ok, queued, session_id} → hook 의 curl 성공 종료.

실행:
  python main.py                                       # :14210, 캡처+리포트
  python main.py --forward http://localhost:14200/v1/sessions   # 실서버로 raw 중계
  Docker 로도 기동 가능 (Dockerfile 참조).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from transcript import extract_meta, parse_jsonl, raw_breakdown

# 모듈 전역 설정 (CLI/env 로 채워짐) — 핸들러가 참조.
CONFIG: dict = {
    "captures_dir": Path("captures"),
    "forward_url": "",
    "max_bytes": 64 * 1024 * 1024,  # 수신 페이로드 상한 (OOM 방어). 0 이면 무제한.
}


def _env_int(name: str, default: int) -> int:
    """env 가 비정수여도 기본값으로 안전 폴백 (기동 실패 방지)."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(name: str, fallback: str) -> str:
    name = _SAFE_NAME.sub("_", (name or "").strip()) or fallback
    return name[:120]


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Handler(BaseHTTPRequestHandler):
    server_version = "AXLocalVerifier/1.0"

    # 기본 BaseHTTPRequestHandler 로그(=stderr 한 줄)는 리포트와 섞여 시끄러움 → 죽인다.
    def log_message(self, *args) -> None:  # noqa: D401
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/health", ""):
            self._json(200, {"ok": True})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/sessions":
            self._json(404, {"ok": False, "error": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        max_bytes = CONFIG["max_bytes"]
        if max_bytes and length > max_bytes:
            self._json(
                413, {"ok": False, "error": f"payload too large (> {max_bytes} bytes)"}
            )
            return
        payload: bytes = self.rfile.read(length) if length else b""
        user_id = self.headers.get("X-User-Id", "")
        session_id = self.headers.get("X-Session-Id", "") or "no-session"
        cwd = self.headers.get("X-Cwd", "")

        if not payload:
            self._json(400, {"ok": False, "error": "empty transcript body"})
            return

        # 실제 서버처럼 즉시 응답(hook 종료 비차단). 저장/리포트는 응답 전에 처리해도
        # 로컬 검증에선 수십 ms.
        try:
            self._handle(payload, user_id=user_id, session_id=session_id, cwd=cwd)
        except Exception as e:  # noqa: BLE001 — 검증 서버는 절대 hook 을 깨지 않는다
            print(f"[verify] !! 처리 실패: {e}", file=sys.stderr, flush=True)

        self._json(200, {"ok": True, "queued": True, "session_id": session_id})

    def _handle(
        self, payload: bytes, *, user_id: str, session_id: str, cwd: str
    ) -> None:
        captures: Path = CONFIG["captures_dir"]
        captures.mkdir(parents=True, exist_ok=True)
        stem = _safe(session_id, "no-session")

        transcript = parse_jsonl(payload)
        breakdown = raw_breakdown(transcript)
        meta = extract_meta(transcript)

        # 1) raw 원문 그대로 저장 (hook 이 보낸 바이트)
        (captures / f"{stem}.jsonl").write_bytes(payload)

        # 2) 헤더·분해 메타 사이드카
        meta_sidecar = {
            "received_at": _now_iso(),
            "headers": {"X-User-Id": user_id, "X-Session-Id": session_id, "X-Cwd": cwd},
            "received_bytes": len(payload),
            "transcript_lines": len(transcript),
            "raw_breakdown": breakdown,
            "meta": meta,
        }
        (captures / f"{stem}.meta.json").write_text(
            json.dumps(meta_sidecar, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 3) 실제 백엔드로 raw 중계 (옵션)
        forward_status = self._forward(
            payload, user_id=user_id, session_id=session_id, cwd=cwd
        )

        _print_report(
            user_id=user_id,
            session_id=session_id,
            cwd=cwd,
            n_bytes=len(payload),
            n_lines=len(transcript),
            breakdown=breakdown,
            meta=meta,
            stem=stem,
            forward_status=forward_status,
        )

    def _forward(self, payload: bytes, *, user_id: str, session_id: str, cwd: str):
        url = CONFIG["forward_url"]
        if not url:
            return None
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/x-ndjson",
                "X-User-Id": user_id,
                "X-Session-Id": session_id,
                "X-Cwd": cwd,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                return f"{resp.status} {resp.read().decode('utf-8', 'replace')[:200]}"
        except Exception as e:  # noqa: BLE001
            return f"ERROR {e}"


def _print_report(
    *,
    user_id,
    session_id,
    cwd,
    n_bytes,
    n_lines,
    breakdown,
    meta,
    stem,
    forward_status,
) -> None:
    b = breakdown
    lines = [
        "",
        "┌─ ax-monitor 수신 검증 ───────────────────────────────────",
        f"│ user={user_id or '(none)'}  session={session_id}",
        f"│ cwd={cwd or '(none)'}",
        f"│ 수신 {n_bytes:,} bytes / {n_lines} lines",
        f"│ 발화 {b['user_messages']} / 응답 {b['assistant_messages']} / "
        f"tool_use {b['tool_use']} / tool_result {b['tool_result']} / "
        f"skill {b['skill_calls']} / agent {b['agent_calls']}",
        f"│ tools={meta['tools_used']}",
        f"│ skills={meta['skills_used']}  sub_agents={meta['sub_agents_used']}",
        f"│ turns={meta['turns']}  tokens={meta['tokens']:,}",
    ]
    if forward_status is not None:
        lines.append(f"│ forward → {forward_status}")
    lines.append(f"│ 저장: captures/{stem}.jsonl + captures/{stem}.meta.json")
    lines.append("└──────────────────────────────────────────────────────────")
    print("\n".join(lines), flush=True)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ax-monitor 로컬 검증 서버 (raw 캡처/중계)")
    p.add_argument("--host", default=os.getenv("AX_VERIFY_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=_env_int("AX_VERIFY_PORT", 14210))
    p.add_argument(
        "--captures-dir", default=os.getenv("AX_VERIFY_CAPTURES", "captures")
    )
    p.add_argument(
        "--max-bytes",
        type=int,
        default=_env_int("AX_VERIFY_MAX_BYTES", 64 * 1024 * 1024),
        help="수신 페이로드 상한 바이트(OOM 방어). 0 이면 무제한",
    )
    p.add_argument(
        "--forward",
        default=os.getenv("AX_VERIFY_FORWARD", ""),
        help="동일 raw POST 를 실제 백엔드로 중계 (예: http://localhost:14200/v1/sessions)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    CONFIG["captures_dir"] = Path(args.captures_dir)
    CONFIG["forward_url"] = args.forward
    CONFIG["max_bytes"] = args.max_bytes
    CONFIG["captures_dir"].mkdir(parents=True, exist_ok=True)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"[verify] ax-monitor 로컬 검증 서버 → http://{args.host}:{args.port}/v1/sessions\n"
        f"[verify]   captures={CONFIG['captures_dir'].resolve()}  "
        f"forward={CONFIG['forward_url'] or '-'}\n"
        f"[verify]   hook 에서: export AX_SUMMARIZER_URL=http://localhost:{args.port}/v1/sessions",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[verify] 종료", flush=True)
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
