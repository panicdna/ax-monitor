# ax-monitor local verifier

ax-monitor hook 의 **전송 대상**을 풀 백엔드(Postgres·시드·아바타 서비스) 없이 로컬에서
띄워, hook 이 실제로 무엇을 보내는지·OpenAI 요약 경로가 도는지를 검증하는 **단일 파일 stdlib
서버**(외부 의존 0). 설치 시 `~/.claude/ax-monitor/local-verifier/` 로 복사됩니다.

## 무엇을 하나

`POST /v1/sessions` 로 들어온 hook 전송을 받아:

1. raw body(transcript JSONL) + 헤더(`X-User-Id`/`X-Session-Id`/`X-Cwd`)를
   `captures/<session>.jsonl` + `.meta.json` 으로 **그대로 저장**.
2. 측정 서버와 **동일한 메타 분해**(발화/응답/tool_use/tool_result/skill/agent,
   tools·skills·sub_agents·turns·tokens)를 stdout 리포트로 출력.
3. (`--summarize`) OpenAI 호환 `/chat/completions` 요약 — `LLM_BASE_URL` 미설정 시 stub 폴백.
4. (`--forward <URL>`) 동일 POST 를 실제 백엔드로 중계.

응답은 실제 서버와 동일한 `{"ok":true,"queued":true,...}` 라 hook 의 `curl` 이 성공 종료합니다.

> 견고성: 깨진 JSONL(비-dict `input` 등)에도 분해가 멈추지 않고, 잘못된 env 는 기본값으로
> 폴백, 수신 페이로드는 `--max-bytes`(기본 64MB)로 상한을 둬 OOM 을 막습니다.

## 띄우기

```bash
cd ~/.claude/ax-monitor/local-verifier
python main.py                              # 캡처 + 분해 리포트만
python main.py --summarize                  # 요약 경로까지 (LLM 미설정이면 stub)
python main.py --forward http://<deployed>/v1/sessions   # 로컬 검증 + 실서버 동시
```

Docker(선택):

```bash
docker build -t ax-local-verifier .
docker run --rm -p 14210:14210 -v "$PWD/captures:/app/captures" ax-local-verifier
```

## 옵션 / env

| 플래그 / env | 기본 | 용도 |
| --- | --- | --- |
| `--port` / `AX_VERIFY_PORT` | `14210` | 수신 포트 |
| `--host` / `AX_VERIFY_HOST` | `0.0.0.0` | 바인드 호스트 |
| `--captures-dir` / `AX_VERIFY_CAPTURES` | `captures` | 캡처 저장 위치 |
| `--summarize` / `AX_VERIFY_SUMMARIZE` | off | 요약 경로 시험 |
| `--forward` / `AX_VERIFY_FORWARD` | (없음) | 실서버 중계 URL |
| `--max-bytes` / `AX_VERIFY_MAX_BYTES` | `67108864`(64MB) | 수신 상한(초과 413). 0=무제한 |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | (없음) | OpenAI 호환 요약(비우면 stub) |
| `LLM_RESPONSE_FORMAT` | `json_schema` | `json_schema` \| `json_object` \| `text` |
| `LLM_MAX_TOKENS` / `LLM_TIMEOUT_S` | `2800` / `30` | 토큰/타임아웃(비정수면 폴백) |

> 캡처에는 세션 원문이 들어가므로 `captures/` 는 추적하지 않습니다(`.gitignore`).
