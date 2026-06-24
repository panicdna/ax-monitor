# ax-monitor-server (retail server runtime)

ax-monitor hook 의 **전송 대상** — raw 세션 기록을 받아 캡처·분해하고, 옵션으로 요약·중계
하며, 읽기 전용 대시보드를 제공하는 **단일 파일 stdlib 서버**(외부 의존 0, Python ≥ 3.10).
`/install-ax-server` 가 이 디렉터리를 `~/.claude/ax-monitor-server/` 로 복사하고 nohup 데몬으로
띄웁니다.

## 무엇을 하나

`POST /v1/sessions` 로 들어온 hook 전송을 받아:

1. raw body(transcript JSONL) + 헤더(`X-User-Id`/`X-Session-Id`/`X-Cwd`)를
   `captures/<session>.{jsonl,meta.json}` 로 **그대로 저장**.
2. 결정적 분해(발화/응답/tool_use/tool_result/skill/agent, tools·skills·sub_agents·turns·
   tokens)를 stdout 리포트로 출력.
3. (`--summarize`) OpenAI 호환 `/chat/completions` 요약 — `LLM_BASE_URL` 없으면 결정적 stub.
4. (`--forward <URL>`) 동일 raw POST 를 상위/다른 서버로 중계.

또한 `GET /` `/admin` `/dashboard` 로 읽기 전용 대시보드를, `GET /api/sessions[/<stem>]` 로
캡처된 세션을 JSON 으로 제공합니다. 응답은 항상 `{"ok":true,"queued":true,...}` 라 hook 의
`curl` 이 성공 종료합니다(세션 종료 비차단).

## 런처로 관리 (설치 후)

```bash
~/.claude/ax-monitor-server/ax-server.sh start     # nohup 백그라운드 기동
~/.claude/ax-monitor-server/ax-server.sh status    # 실행 여부 + /health
~/.claude/ax-monitor-server/ax-server.sh restart    # 재시작(설정 변경 반영)
~/.claude/ax-monitor-server/ax-server.sh stop       # 종료
```

런처는 설치 시 기록된 `ax-server.env`(같은 디렉터리)를 매 호출마다 source 하므로, 위 명령들은
env 프리픽스 없이 동작합니다. 설정 변경은 그 파일을 고치고 `restart`. 설정 키(`AX_SERVER_*`):

| env | 기본 | 용도 |
| --- | --- | --- |
| `AX_SERVER_HOST` | `0.0.0.0` | 바인드 IP(인터페이스) |
| `AX_SERVER_PORT` | `14200` | 수신 포트 |
| `AX_SERVER_SUMMARIZE` | (없음) | `1` 이면 `--summarize` |
| `AX_SERVER_FORWARD` | (없음) | 값 있으면 `--forward <URL>` |
| `AX_SERVER_CAPTURES` | `<설치dir>/captures` | 캡처 저장 위치 |
| `AX_SERVER_LOG` | `~/.claude/ax-server.log` | 서버 stdout 로그 |

## 직접 실행 (런처 없이)

```bash
cd ~/.claude/ax-monitor-server
python3 main.py                       # :14200, 캡처+리포트
python3 main.py --summarize           # 요약 경로까지(LLM_BASE_URL 있으면 OpenAI)
python3 main.py --port 14201          # 포트 변경
python3 main.py --forward http://<upstream>/v1/sessions
```

> 견고성: 깨진 JSONL(비-dict `input` 등)에도 분해가 멈추지 않고, 잘못된 env 는 기본값으로
> 폴백, 수신 페이로드는 `--max-bytes`(기본 64MB)로 상한을 둬 OOM 을 막습니다.
> 캡처에는 세션 원문이 들어가므로 `captures/` 는 추적하지 마세요.

> nohup 데몬이라 **재부팅 시 자동 기동되지 않습니다** — 부팅 후 `ax-server.sh start` 를 다시
> 실행하거나 셸 프로필/`@reboot` cron 에 등록하세요.
