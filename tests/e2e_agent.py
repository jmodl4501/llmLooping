#!/usr/bin/env python3
"""
e2e_agent.py — agent.py 전체 루프 E2E 검증.

모의 웹 LLM(agent 모드)에 대해 실제 agent.py를 subprocess로 실행하고,
다음 시나리오가 끝까지 동작하는지 확인한다:

  step1  goal 전송 → 모의 LLM이 ```file hello.txt``` 액션 응답 → 파일 작성
  step2  결과 피드백 → 실패하는 ```run``` 액션 응답 → 오류 결과 피드백
  step3  오류 피드백 → 성공하는 ```run``` 액션 응답 → 출력 피드백
  step4  출력 피드백 → [DONE] 응답 → agent.py 정상 종료

추가로 Chrome 자동 기동 경로(attach 실패 → launch)도 함께 검증한다.

실행: python tests/e2e_agent.py
사전 준비: pip install -r requirements.txt && playwright install chromium
"""

import os
import subprocess as sp
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mock_llm  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main():
    server = mock_llm.create_server("agent")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"[e2e-agent] 모의 LLM: {site} (mode=agent)")

    with sync_playwright() as pw:
        chrome_exe = pw.chromium.executable_path

    workspace = Path(tempfile.mkdtemp(prefix="llm-agent-ws-"))
    env = dict(os.environ)
    env.update(
        CDP_PORT="9231",
        LLM_ORIGIN=site,
        LLM_START_URL=site + "/",
        CHROME_BIN=chrome_exe,
        AGENT_HEADLESS="1",
        AGENT_CLOSE_BROWSER="1",
        AGENT_WORKSPACE=str(workspace),
        AGENT_MAX_STEPS="10",
        APPROVAL="auto",
        RESPONSE_TIMEOUT="120",
        STABLE_POLLS="3",
        EDITOR_CSS="#prompt-textarea",
        REPLY_CSS='[data-message-author-role="assistant"]',
    )
    cp = sp.run(
        [sys.executable, str(ROOT / "agent.py")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
    )
    print("--- agent stdout ---")
    print(cp.stdout)
    if cp.stderr.strip():
        print("--- agent stderr ---", file=sys.stderr)
        print(cp.stderr, file=sys.stderr)

    hello = workspace / "hello.txt"
    assert cp.returncode == 0, "agent.py가 정상 종료해야 함"
    assert hello.exists(), "hello.txt가 작업 폴더에 생성되어야 함"
    assert hello.read_text(encoding="utf-8").strip() == "hello arena agent"
    assert len(server.submissions) == 4, f"4회 제출되어야 함: {len(server.submissions)}"
    assert "[목표]" in server.submissions[0], "첫 제출은 목표 프롬프트"
    assert "[작성 완료]" in server.submissions[1], "파일 작성 결과가 피드백되어야 함"
    assert "exit=" in server.submissions[2], "실패 명령의 exit 코드가 피드백되어야 함"
    assert "hello arena agent" in server.submissions[3], "성공 출력이 피드백되어야 함"
    logs = list((ROOT / "runs").glob("agent-*/step-*.response.txt"))
    assert len(logs) >= 4, "스텝별 로그가 runs/에 남아야 함"

    server.shutdown()
    print("[e2e-agent] PASS — 파일 작성/실패 피드백/성공 실행/[DONE] 종료 모두 검증")


if __name__ == "__main__":
    main()
