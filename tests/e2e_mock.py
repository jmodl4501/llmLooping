#!/usr/bin/env python3
"""
e2e_mock.py — 전체 루프 E2E 검증.

모의 웹 LLM 서버 + CDP로 띄운 Chromium + 실제 controller.py를 조합해
다음을 끝까지 검증한다:

  fixable 모드 (기본)
    1회차: 일부러 틀린 ZIP → 검증 실패 → 피드백이 같은 대화로 돌아감
    2회차: 수정된 ZIP → 모든 case 통과 → PASS 종료
  broken 모드
    매 회차 틀린 ZIP → 최대 회차 도달 → FAIL 종료

실행:
    python tests/e2e_mock.py [fixable|broken]

사전 준비: pip install -r requirements.txt && playwright install chromium
Docker는 필요하지 않다(컨트롤러를 RUNNER=local 로 구동).
"""

import json
import os
import shutil
import subprocess as sp
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mock_llm  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CDP_PORT = int(os.getenv("TEST_CDP_PORT", "9229"))


def wait_for(url, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(0.3)
    raise SystemExit(f"시간 초과: {url} 응답 없음")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "fixable"
    max_rounds = "4" if mode == "fixable" else "2"

    # 1) 모의 웹 LLM 서버 시작
    server = mock_llm.create_server(mode)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"[e2e] 모의 LLM: {site} (mode={mode})")

    # 2) CDP 포트로 Chromium 실행 후 모의 LLM 탭 오픈
    with sync_playwright() as pw:
        chrome_exe = pw.chromium.executable_path
    profile = tempfile.mkdtemp(prefix="llm-e2e-profile-")
    chrome = sp.Popen(
        [
            chrome_exe,
            "--headless=new",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={profile}",
            site + "/",
        ],
        stdout=sp.DEVNULL,
        stderr=sp.DEVNULL,
    )
    try:
        wait_for(f"http://127.0.0.1:{CDP_PORT}/json/version")
        tabs = wait_for(f"http://127.0.0.1:{CDP_PORT}/json/list")
        if not any(t.get("url", "").startswith(site) for t in tabs):
            raise SystemExit("모의 LLM 탭이 열리지 않았습니다.")
        print(f"[e2e] Chromium CDP: 127.0.0.1:{CDP_PORT}")

        # 3) 컨트롤러를 실제 subprocess로 실행 (테스트용 RUNNER=local)
        env = dict(os.environ)
        env.update(
            CDP_PORT=str(CDP_PORT),
            LLM_ORIGIN=site,
            EDITOR_CSS="#prompt-textarea",
            REPLY_CSS='[data-message-author-role="assistant"]',
            ZIP_ROLE="link",
            RUNNER="local",
            MAX_ROUNDS=max_rounds,
        )
        cp = sp.run(
            [sys.executable, str(ROOT / "controller.py")],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
        )
        print("--- controller stdout ---")
        print(cp.stdout)
        if cp.stderr.strip():
            print("--- controller stderr ---", file=sys.stderr)
            print(cp.stderr, file=sys.stderr)

        # 4) 결과 검증
        if mode == "fixable":
            assert cp.returncode == 0 and "PASS" in cp.stdout, "PASS로 종료해야 함"
            assert len(server.submissions) == 2, f"2회차까지 제출되어야 함: {len(server.submissions)}"
            assert "최초 회차" in server.submissions[0], "1회차는 최초 프롬프트"
            assert "검증 case-1 실패" in server.submissions[1], (
                "2회차 프롬프트에 직전 실패 피드백이 포함되어야 함"
            )
            assert "누락 또는 값이 잘못된 필드" in cp.stdout, "실패 원인 요약이 출력되어야 함"
            src = list((ROOT / "runs").glob("*/*/project/main.py"))
            assert src, "검증 통과 프로젝트 소스가 runs/에 남아야 함"
            case_logs = list((ROOT / "runs").glob("*/*/case-*.stdout.txt"))
            assert case_logs, "케이스 실행 로그가 남아야 함"
            print("[e2e] fixable 시나리오 검증 통과")
        else:
            combined = cp.stdout + cp.stderr
            assert cp.returncode != 0 and "FAIL" in combined, "FAIL로 종료해야 함"
            assert len(server.submissions) == int(max_rounds), "최대 회차만큼 제출"
            print("[e2e] broken 시나리오 검증 통과")

        print(f"[e2e] PASS ({mode}) — submissions={len(server.submissions)}건")
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except sp.TimeoutExpired:
            chrome.kill()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
