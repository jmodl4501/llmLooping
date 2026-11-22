# llm-loop

웹 LLM(Arena.ai 등)을 Playwright + CDP로 조작하는 두 가지 자동화 루프입니다.

| 스크립트 | 방식 | 비유 |
|---|---|---|
| **agent.py** | 목표 전송 → 응답의 액션(명령/파일 작성)을 로컬 작업 폴더에서 실행 → 결과를 같은 대화에 피드백 → 반복 | Claude Code / Codex CLI |
| **controller.py** | 목표 전송 → 전체 프로젝트 ZIP 수신 → 격리 실행·검증 → 실패 시 피드백 후 재생성 | 단일 산출물 검증 파이프라인 |

> **전제**: 자동화가 허용되는 서비스에서만 사용하세요.

## Windows 빠른 시작 (agent.py)

```bat
1. setup.bat          ← 최초 1회: 가상환경 + 패키지 설치 + config.env 생성
2. goal-agent.txt     ← 메모장으로 열어 시킬 작업(목표) 작성
3. run-agent.bat      ← 실행 (Chrome이 없으면 자동으로 띄움)
```

- 첫 실행 시 Chrome이 열리면 **Arena 로그인 후 Agent Mode 대화 화면**을 열어 두세요. 컨트롤러가 입력창을 찾을 때까지 자동으로 대기합니다.
- 종료 조건: LLM이 `[DONE]` 출력, 또는 `AGENT_MAX_STEPS` 도달.
- 산출물은 `workspace/`, 스텝별 요청·응답·결과 로그는 `runs/agent-*/`에 남습니다.

## 동작 구조 (agent.py)

```text
run-agent.bat
   │
   ├─ Chrome CDP 확인 → 없으면 자동 실행(전용 프로필) → 있으면 attach
   ├─ arena.ai/agent 탭 탐색 (없으면 새 탭) → 입력창 대기(로그인 시간 확보)
   │
   │  ┌──────────────────────────────────────────────┐
   │  │ step N                                       │
   │  │  1. goal + 행동 계약(agent_prompt.txt) 전송   │
   │  │  2. 응답 대기 (스트리밍 안정화 감지)           │
   │  │  3. 액션 파싱:                                │
   │  │       ```run <명령>        → cmd.exe 실행    │
   │  │       ```file <경로>       → workspace에 저장 │
   │  │       [DONE]               → 종료             │
   │  │  4. 실행 결과(stdout/stderr/exit)를           │
   │  │     같은 대화에 피드백으로 전송               │
   │  └──────────────────────────────────────────────┘
   └─ 최대 스텝 도달 시 중단
```

## 설정 — config.env

`setup.bat`이 `config.env.example`을 복사해 만듭니다. 메모장으로 편집하세요.

| 키 | 기본값 | 설명 |
|---|---|---|
| `LLM_ORIGIN` | `https://arena.ai` | 웹 LLM 출처 |
| `LLM_START_URL` | `https://arena.ai/agent` | 탭이 없을 때 열 주소 |
| `CDP_PORT` | `9222` | Chrome CDP 포트 |
| `CHROME_BIN` | (자동 탐지) | Chrome 경로 |
| `EDITOR_CSS` / `REPLY_CSS` / `SEND_CSS` | (자동 후보 시도) | 입력창/응답영역/전송버튼 선택자. 자동 탐지 실패 시에만 지정 |
| `AGENT_WORKSPACE` | `workspace` | 에이전트 작업 폴더 |
| `AGENT_MAX_STEPS` | `30` | 최대 스텝 |
| `RESPONSE_TIMEOUT` | `1800` | 응답 대기 상한(초). Agent Mode는 수 분 걸릴 수 있음 |
| `EXEC_TIMEOUT` | `120` | 명령 1회 실행 상한(초) |
| `APPROVAL` | `auto` | `auto`=완전 자동 / `smart`=위험 명령만 확인 / `ask`=매번 확인 |
| `RUNNER` | `docker` | controller.py 실행기: `docker`(격리) / `local`(테스트 전용) |
| `MAX_ROUNDS` / `JOB_IMAGE` | `4` / `python:3.12-slim` | controller.py 회차/이미지 |

## 액션 계약 (LLM 응답 형식)

`agent_prompt.txt`가 LLM에게 요구하는 형식입니다. 한 응답에 액션 하나:

<pre>
```run
dir
```
```file src/main.py
print("hi")
```
[DONE]
</pre>

- `run`: 작업 폴더에서 셸 명령 실행. stdout/stderr/exit code가 다음 메시지로 전달됩니다.
- `file`: 작업 폴더 기준 상대 경로에 전체 내용 저장(상위 폴더 자동 생성, 폴더 밖 경로 차단).
- `[DONE]`: 마지막 줄에 단독으로. 수신 시 루프 종료.

## 안전 장치

- `APPROVAL=auto`라도 **OS·데이터 파괴 명령 차단 목록**(format, diskpart, shutdown, `rm -rf /`, 루트 `rd /s /q` 등)은 항상 적용됩니다. 차단되면 LLM에게 "차단됨"이 피드백됩니다.
- 파일 쓰기는 `workspace` 밖으로 나갈 수 없습니다(경로 탈출 차단).
- 명령 출력은 4,000자로 잘라서 보냅니다(원본은 `runs/` 로그에 보존).
- CDP 포트는 `127.0.0.1`에만 바인딩됩니다. 외부에 공개하지 마세요.
- 에이전트가 실행하는 명령은 **로그인된 내 PC에서 그대로 실행**됩니다. `auto` 외에 `smart`/`ask` 모드도 있으니 목표에 맞게 선택하세요.

## controller.py (ZIP 검증 루프)

단일 완성 프로젝트를 ZIP으로 받아 **격리 실행 후 완료 기준(`cases/`)으로 검증**하는 루프입니다. Docker Desktop(리눅스 컨테이너 모드)이 필요합니다.

```bat
run-controller.bat     ← goal.txt 와 cases/ 를 편집한 뒤 실행
```

상세 동작(2MB ZIP 제한, 파일 3종 고정, `--network=none` 컨테이너 등)은 코드 주석을 참고하세요. Docker가 없으면 `RUNNER=local`(테스트 전용 비격리)로 루프만 검증할 수 있습니다.

## 폴더 구조

```text
llm-loop/
├── agent.py               # 에이전트 루프 (신규)
├── agent_prompt.txt       # 에이전트 행동 계약 템플릿
├── goal-agent.txt         # ← 에이전트에게 시킬 목표
├── controller.py          # ZIP 검증 루프
├── prompt.txt / goal.txt  # ZIP 루프용 프롬프트/목표
├── cases/                 # ZIP 루프 완료 기준
├── config.py              # config.env 로더
├── config.env.example     # 설정 템플릿
├── setup.bat / start-chrome.bat / run-agent.bat / run-controller.bat
├── workspace/             # 에이전트 작업 폴더
├── scripts/               # chrome-cdp.ps1 / chrome-cdp.sh
└── tests/                 # 단위 + 모의 E2E (아래 참고)
```

## 테스트 (개발용)

```bash
pip install -r requirements.txt
playwright install chromium

python tests/test_core.py        # 단위: ZIP 검증/완료 판정
python tests/e2e_mock.py fixable # ZIP 루프 E2E: 실패 → 피드백 → PASS
python tests/e2e_mock.py broken  # ZIP 루프 E2E: 최대 회차 후 FAIL
python tests/e2e_agent.py        # 에이전트 루프 E2E: file/run/[DONE] 전 과정
```

테스트는 모두 모의 웹 LLM 서버 + CDP로 띄운 Chromium + 실제 스크립트를 사용하며 Docker 없이 동작합니다.

## 실제 목적에 적용할 때 바꿀 곳

| 바꿀 곳 | 넣을 내용 |
|---|---|
| `goal-agent.txt` | 에이전트에게 시킬 작업(테스트 코드 작성, 환경 구축, 문서 생성 등) |
| `agent_prompt.txt` | 액션 형식·제약을 바꾸고 싶을 때 |
| `goal.txt` / `cases/` | ZIP 루프의 목적과 완료 기준 |
| `config.env` | 서비스 변경(LLM_ORIGIN), 선택자, 승인 정책, 스텝/시간 제한 |

폼 제출·게시·결제처럼 외부 상태를 바꾸는 명령은 루프 안에서 중복 실행될 수 있습니다. 그런 작업은 `APPROVAL=smart` 이상으로 두세요.
