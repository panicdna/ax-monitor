# ax-monitor

사용자 워크플로우를 **전혀 바꾸지 않고** Claude Code 사용을 중앙에서 관측하기 위한
[Claude Code](https://docs.claude.com/en/docs/claude-code) 플러그인 마켓플레이스입니다.
세션이 끝날 때(`SessionEnd`) 또는 매 응답 종료마다(`Stop`) 그 세션의 transcript 를 측정
서버로 **raw 그대로** 한 번 보냅니다(클라이언트에선 파싱·LLM 없이 업로드만). 무엇을
보존/추출할지는 전적으로 서버 몫입니다. 사용자는 평소처럼 `claude` 만 쓰면 됩니다 — 전송은
서버가 수신 즉시 응답하므로 체감 0, 실패/지연해도 세션 종료를 막지 않습니다.

> 동작 흐름: `평소처럼 claude 작업 → 세션/턴 종료 → (자동) hook 이 transcript 전송 → 끝`.
> hook 은 가볍습니다 — 파싱·LLM 호출을 PC 에서 하지 않고 파일을 그대로 업로드만 합니다.
> 무엇을 쓸지 고르는 일은 전부 서버 몫입니다.

관리: [@panicdna](https://github.com/panicdna). `jq` 와 `curl` 이 필요합니다.

---

## 설치는 어떻게 동작하나

설치는 **두 개의 층**입니다.

**1. 마켓플레이스 등록 — 딱 한 번:**

```
/plugin marketplace add panicdna/ax-monitor
```

**2. 그다음 플러그인 두 단계:**

- `/plugin install ax-monitor` — 플러그인의 스킬을 내 환경으로 가져옵니다 (이것만으론 측정이
  켜지지 **않습니다**).
- `/install-ax-monitor` — 번들 hook 을 `~/.claude/ax-monitor/` 로 복사하고
  `~/.claude/settings.json` 에 hook 을 실제로 작성합니다.

**제거는 역순:**

- `/uninstall-ax-monitor` — 이 플러그인의 hook 을 `settings.json` 에서 제거합니다.
- `/plugin uninstall ax-monitor` — 플러그인 패키지를 제거합니다.

> ⚠️ 반드시 `/uninstall-ax-monitor` 를 `/plugin uninstall` **보다 먼저** 실행하세요. 먼저
> 패키지를 지우면 hook 이 `settings.json` 에 "유령 hook" 으로 남습니다.

| 플러그인 | 플러그인 층 | 설치 스킬 | 제거 스킬 |
|---|---|---|---|
| `ax-monitor` | `/plugin install ax-monitor` / `/plugin uninstall ax-monitor` | `/install-ax-monitor` | `/uninstall-ax-monitor` |

---

## `ax-monitor` — 세션 측정 hook

| 스킬 | 트리거 | 동작 |
|---|---|---|
| `install-ax-monitor` | `/install-ax-monitor` | 사전 점검 → 런타임 복사 → **대화식 설정**(서버 URL·이벤트·턴 분리·user id) → 서버 연결 확인 → settings.json hook 병합 → 리로드 안내 |
| `uninstall-ax-monitor` | `/uninstall-ax-monitor` | 자기 hook 만 제거(다른 hook 불침해) → 런타임·로그 삭제 선택 → 리로드 안내 |

설치는 **대화식** 입니다 — Claude 의 질문 UI 로 다음을 물어봅니다:

| 설정 | 옵션 | 기본값 |
|---|---|---|
| 측정 서버 URL (`AX_SUMMARIZER_URL`) | 로컬 verifier(`:14210`) / 배포 서버 URL | 로컬 verifier |
| 발사 이벤트 | `SessionEnd`(세션 1회) / `Stop`(매 턴) / 둘 다 | `SessionEnd` |
| 턴 분리 (`AX_PER_TURN`) | off(세션=한 행) / on(`-tNNN` 별도 행) | off |
| user id (`AX_USER_ID`) | `whoami` / 커스텀(Knox 메일 등) | `whoami` |

Hook: `SessionEnd`/`Stop` 가 transcript 를 `AX_SUMMARIZER_URL` 로 POST 합니다. 둘 다 멱등이며
고유 문자열 `ax-monitor/ax_session_end` 로 식별되므로, 제거 시 무관한 hook 은 절대 건드리지
않습니다.

**설치:**

```
/plugin marketplace add panicdna/ax-monitor   # 한 번만; 이미 등록했다면 생략
/plugin install ax-monitor
/install-ax-monitor
```

설치 스킬이 서버 URL·이벤트·턴 분리·user id 를 물어본 뒤 hook 을 병합합니다. **`/hooks` 를
한 번 열었다 닫아 리로드**하세요(Claude Code 는 settings.json 을 세션 시작 시 캐시하므로,
세션 중 변경은 다음 세션 또는 리로드부터 적용됩니다).

**요구사항:** `jq`, `curl` (`sudo apt install -y jq curl`).

**제거:** `/uninstall-ax-monitor` 후 `/plugin uninstall ax-monitor`. 런타임·로그를 지우기
전에 물어봅니다.

### 호출 로그로 진단하기

hook 은 불릴 때마다 `~/.claude/ax-hook.log` 에 한 줄씩 남깁니다(도착 여부와 무관):

```
2026-06-23 14:59:38 [ax-hook] invoked pid=1492812 cwd=/...
2026-06-23 14:59:38 [ax-hook] send   session=<id> user=<u> bytes=<n> url=http://localhost:14210/v1/sessions
2026-06-23 14:59:39 [ax-hook] result session=<id> http=200 curl_exit=0
```

`http=000 curl_exit≠0` 이면 "hook 은 불렸지만 측정 서버가 안 떠 있었다" 는 뜻입니다(세션은
막지 않음). `invoked` 줄이 안 늘면 hook 이 아예 안 불린 것(설정 리로드 전이거나 이벤트 미발생).

---

## 번들 로컬 verifier — 풀 백엔드 없이 시험

`runtime/local-verifier/` 는 외부 의존 0의 **단일 파일 stdlib 서버**입니다. 설치 시
`~/.claude/ax-monitor/local-verifier/` 로 함께 복사됩니다. hook 이 보낸 raw transcript +
헤더를 그대로 저장하고, "무엇이 들어왔나"를 결정적 분해 리포트로 출력하며, 실서버로 raw
그대로 중계(`--forward`)할 수 있습니다. LLM/요약은 없습니다.

```bash
# 로컬 검증 대상 띄우기 (캡처 + 분해 리포트)
python ~/.claude/ax-monitor/local-verifier/main.py

# 로컬 + 실서버 동시 확인 (raw 중계)
python ~/.claude/ax-monitor/local-verifier/main.py --forward http://<deployed>/v1/sessions
```

자세한 옵션은 [`plugins/ax-monitor/runtime/local-verifier/README.md`](./plugins/ax-monitor/runtime/local-verifier/README.md).

---

## 저장소 구조

```
ax-monitor/
├── .claude-plugin/
│   └── marketplace.json                     # 마켓플레이스 매니페스트
├── plugins/
│   └── ax-monitor/
│       ├── .claude-plugin/plugin.json
│       ├── runtime/                         # 설치 시 ~/.claude/ax-monitor/ 로 복사됨
│       │   ├── ax_session_end.sh            # SessionEnd/Stop hook (hook 이 호출)
│       │   └── local-verifier/              # 번들 stdlib 검증 서버 (선택)
│       │       ├── main.py · transcript.py
│       │       ├── requirements.txt · Dockerfile · README.md
│       └── skills/
│           ├── install-ax-monitor/SKILL.md
│           └── uninstall-ax-monitor/SKILL.md
├── README.md
└── LICENSE
```

## 설계 노트

- **멱등 설치** — 설치 스킬을 다시 실행하면 제거 없이 그 자리에서 재설정됩니다(서버 URL·이벤트·
  턴 분리·user id 변경).
- **설정 쓰기 전 검증** — 서버가 떠 있으면 작은 합성 transcript 로 test-fire 해 `http=200` 을
  확인한 뒤 settings.json 에 씁니다(서버가 꺼져 있으면 경고만, 등록은 진행).
- **분리된 식별 시그니처** — hook 명령은 `ax-monitor/ax_session_end` 를 포함합니다. 제거는
  이 시그니처 hook 만 정확히 지우므로 다른 hook 과 공존합니다.
- **개인정보 경계** — hook 은 transcript 파일을 그대로 업로드만 합니다. 무엇을 보존/폐기·
  가공할지는 전적으로 서버가 정합니다(클라이언트와 이 번들 verifier 는 LLM 을 호출하지 않음).

## 라이선스

MIT — [LICENSE](./LICENSE) 참고.
