#!/usr/bin/env python3
"""
agent.py — 웹 LLM(Arena.ai Agent Mode 등)을 두뇌로 쓰는 로컬 에이전트 루프.

Claude Code / Codex CLI처럼 동작한다:

  목표 전송 → 응답의 액션(```run 명령 / ```file 파일 작성)을 로컬 작업 폴더에서 실행
  → 실행 결과를 같은 대화에 피드백 → 반복 → [DONE] 또는 최대 스텝에서 종료

Chrome이 CDP 포트에 없으면 직접 띄우고, 이미 떠 있으면 그대로 붙는다(attach).

설정은 config.env (없으면 환경변수)로 한다. config.env.example 참고.
실행: python agent.py
"""

import os
import re
import shutil
import subprocess as sp
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from config import load_config

load_config()

ROOT = Path(__file__).resolve().parent
CDP_PORT = int(os.getenv("CDP_PORT", "9222"))
MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "30"))
RESPONSE_TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "1800"))
EXEC_TIMEOUT = float(os.getenv("EXEC_TIMEOUT", "120"))
APPROVAL = os.getenv("APPROVAL", "auto").lower()  # auto | smart | ask
POLL = 1.0
STABLE_POLLS = int(os.getenv("STABLE_POLLS", "5"))  # 텍스트가 이 횟수 연속 같으면 응답 완료

_ws = os.getenv("AGENT_WORKSPACE", "workspace")
WORKSPACE = (ROOT / _ws).resolve() if not os.path.isabs(_ws) else Path(_ws).resolve()

# UI 선택자 후보 — 위에서부터 시도. config.env에서 덮어쓸 수 있다.
EDITOR_CANDIDATES = [
    "#prompt-textarea",
    "div[contenteditable='true']",
    "[contenteditable='true']",
    "textarea[placeholder]",
    "textarea",
]
REPLY_CANDIDATES = [
    "[data-message-author-role='assistant']",
    "[class*='assistant']",
    "[class*='agent'][class*='message']",
    "main [class*='message']",
]

# OS·데이터를 파괴하는 명령 차단 목록. auto 모드에서도 차단된다.
DENY = [
    r"(?i)\bformat\s+[a-z]:",
    r"(?i)\bdiskpart\b",
    r"(?i)\bshutdown\b",
    r"(?i)\brestart-computer\b",
    r"(?i)\bbcdedit\b",
    r"(?i)\breg\s+(delete|import)\b",
    r"(?i)\brd\s+/s\s+/q\s+[a-z]:\\?\s*$",
    r"(?i)\brmdir\s+/s\s+/q\s+[a-z]:\\?\s*$",
    r"(?i)\bdel\s+/[sf][^\n]*\b[a-z]:\\",
    r"(?i)\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/(\s|$)",
    r"(?i)\bmkfs\b",
    r"(?i)\bdd\s+if=.*of=/dev/",
]

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]


def origin(url):
    u = urlsplit(url)
    return u.scheme.lower(), u.netloc.lower()


def decode(data):
    for enc in ("utf-8", "cp949"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# 브라우저: 이미 떠 있으면 attach, 없으면 자동 기동
# ---------------------------------------------------------------------------
def find_chrome():
    if exe := os.getenv("CHROME_BIN"):
        return exe
    for p in CHROME_PATHS:
        if Path(p).exists():
            return p
    for name in CHROME_NAMES:
        if found := shutil.which(name):
            return found
    return None


def chrome_profile(port):
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "llm-cdp" / f"profile-{port}"


def ensure_browser(pw, start_url):
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        print(f"[attach] 127.0.0.1:{CDP_PORT} 에 실행 중인 Chrome에 연결했습니다.")
        return browser, None
    except Exception:
        pass

    exe = find_chrome()
    if not exe:
        raise SystemExit(
            "Chrome을 찾을 수 없습니다. config.env의 CHROME_BIN에 경로를 지정하거나, "
            "scripts\\start-chrome.bat 으로 직접 실행하세요."
        )
    args = [
        exe,
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={chrome_profile(CDP_PORT)}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if os.getenv("AGENT_HEADLESS") == "1":  # 테스트용
        args.append("--headless=new")
    args.append(start_url)
    print(f"[launch] Chrome 자동 실행: {exe} (CDP {CDP_PORT})")
    proc = sp.Popen(args, stdout=sp.DEVNULL, stderr=sp.DEVNULL)

    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(0.3)
        try:
            return pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}"), proc
        except Exception:
            continue
    proc.terminate()
    raise SystemExit("Chrome CDP 연결에 실패했습니다.")


def get_page(browser, site, start_url):
    for ctx in browser.contexts:
        for p in ctx.pages:
            if origin(p.url) == site:
                return p
    ctx = browser.contexts[0]
    print(f"[open] 새 탭: {start_url}")
    p = ctx.new_page()
    p.goto(start_url)
    return p


# ---------------------------------------------------------------------------
# 웹 LLM 조작
# ---------------------------------------------------------------------------
def _visible(loc):
    try:
        return loc.count() > 0 and loc.last.is_visible()
    except Exception:
        return False


def wait_editor(page, timeout=900):
    """입력창을 찾을 때까지 대기. 로그인이 필요하면 사용자가 하는 동안 기다린다."""
    css = os.getenv("EDITOR_CSS")
    candidates = [css] if css else EDITOR_CANDIDATES
    deadline = time.time() + timeout
    noticed = False
    while time.time() < deadline:
        for c in candidates:
            loc = page.locator(c).last
            if _visible(loc):
                return loc
        if not noticed:
            print("[대기] 입력창을 찾는 중… 로그인이 안 되어 있다면 방금 연 Chrome에서")
            print("       로그인하고 Agent Mode 대화를 열어주세요. 자동으로 이어갑니다.")
            noticed = True
        time.sleep(3)
    raise SystemExit("중단: 입력창을 찾지 못했습니다. config.env에 EDITOR_CSS를 지정하세요.")


def reply_locator(page):
    css = os.getenv("REPLY_CSS")
    if css:
        return page.locator(css)
    for c in REPLY_CANDIDATES:
        loc = page.locator(c)
        try:
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    return page.locator(REPLY_CANDIDATES[0])


def send(page, editor, text):
    editor.click()
    editor.fill(text)
    if send_css := os.getenv("SEND_CSS"):
        page.locator(send_css).click()
        return
    editor.press("Enter")
    time.sleep(2)
    # Enter로 전송되지 않는 UI 대비: 입력창이 비워지지 않았으면 전송 버튼 후보 클릭
    try:
        leftover = editor.input_value()
    except Exception:
        try:
            leftover = editor.inner_text()
        except Exception:
            leftover = ""
    if leftover.strip():
        for cand in ("button[aria-label*='Send']", "button[aria-label*='send']",
                     "button[aria-label*='전송']", "button[type='submit']"):
            btn = page.locator(cand).first
            try:
                if btn.count() and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    return
            except Exception:
                continue


def wait_response(page, baseline, timeout):
    """새 assistant 메시지가 나타난 뒤 내용이 안정화될 때까지 기다려 본문을 반환."""
    deadline = time.time() + timeout
    loc = reply_locator(page)
    while time.time() < deadline:
        try:
            if loc.count() > baseline:
                break
        except Exception:
            pass
        time.sleep(POLL)
    else:
        raise SystemExit(
            "중단: 응답 대기 시간 초과. 응답 영역 선택자(REPLY_CSS)가 맞는지 확인하세요."
        )

    last, stable = None, 0
    while time.time() < deadline:
        try:
            txt = loc.nth(loc.count() - 1).inner_text()
        except Exception:
            time.sleep(POLL)
            continue
        if txt == last and txt.strip():
            stable += 1
            if stable >= STABLE_POLLS:
                return txt
        else:
            last, stable = txt, 0
        time.sleep(POLL)
    raise SystemExit("중단: 응답이 안정화되지 않았습니다.")


# ---------------------------------------------------------------------------
# 액션 파싱 및 실행
# ---------------------------------------------------------------------------
ACTION_RE = re.compile(r"```(run|file)(?:[ \t]+([^\n`]+))?\r?\n(.*?)```", re.S)
DONE_RE = re.compile(r"(?m)^\s*\[DONE\]\s*$")


def parse_actions(text):
    actions = []
    for m in ACTION_RE.finditer(text):
        kind, arg, body = m.group(1), (m.group(2) or "").strip(), m.group(3)
        if body.endswith("\n"):
            body = body[:-1]
        if kind == "run":
            actions.append(("run", body.strip(), ""))
        else:
            actions.append(("file", arg, body))
    done = bool(DONE_RE.search(text))
    return actions, done


def denied(cmd):
    return any(re.search(p, cmd) for p in DENY)


def approve(prompt):
    if APPROVAL == "auto":
        return True
    try:
        return input(f"{prompt} 실행할까요? [y/N] ").strip().lower() == "y"
    except EOFError:
        return False


def safe_join(rel):
    if not rel:
        raise ValueError("경로 없음")
    p = (WORKSPACE / rel).resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise ValueError("작업 폴더 밖 경로")
    return p


def run_shell(cmd):
    head = f"$ {cmd}"
    if denied(cmd):
        return head + "\n[차단됨] 위험 명령으로 분류되어 실행하지 않았습니다."
    if not approve(head):
        return head + "\n[거부됨] 사용자가 실행을 승인하지 않았습니다."
    print(f"  {head}", flush=True)
    full = f"chcp 65001>nul & {cmd}" if sys.platform == "win32" else cmd
    try:
        cp = sp.run(
            full, shell=True, cwd=WORKSPACE, capture_output=True,
            timeout=EXEC_TIMEOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except sp.TimeoutExpired:
        return head + f"\n[시간 초과] {EXEC_TIMEOUT:.0f}초 안에 끝나지 않아 중단했습니다."
    out, err = decode(cp.stdout), decode(cp.stderr)
    limit = 4000
    if len(out) > limit:
        out = out[:limit] + f"\n…(이하 {len(out) - limit}자 생략)"
    if len(err) > limit:
        err = err[:limit] + f"\n…(이하 {len(err) - limit}자 생략)"
    return f"{head}\nexit={cp.returncode}\n<stdout>\n{out}\n</stdout>\n<stderr>\n{err}\n</stderr>"


def write_file_action(rel, content):
    try:
        p = safe_join(rel)
    except ValueError as e:
        return f"[차단됨] {e}: {rel}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"  [작성] {p.relative_to(WORKSPACE)} ({len(content)}자)", flush=True)
    return f"[작성 완료] {rel} ({len(content)}자)"


# ---------------------------------------------------------------------------
# 메인 루프
# ---------------------------------------------------------------------------
def main():
    site_url = os.getenv("LLM_START_URL") or os.getenv("LLM_ORIGIN", "")
    if not site_url:
        raise SystemExit("config.env에 LLM_ORIGIN(또는 LLM_START_URL)이 필요합니다.")
    site = origin(site_url)

    goal_path = ROOT / "goal-agent.txt"
    template = Template((ROOT / "agent_prompt.txt").read_text(encoding="utf-8-sig"))
    goal = goal_path.read_text(encoding="utf-8-sig")
    os_info = f"Windows ({os.getenv('OS', '')}, cmd.exe)" if sys.platform == "win32" \
        else f"{sys.platform} (POSIX sh)"
    shell = "cmd.exe" if sys.platform == "win32" else "sh"
    first_msg = template.substitute(
        goal=goal, workspace=str(WORKSPACE), os_info=os_info,
        shell=shell, max_steps=MAX_STEPS,
    )

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    logdir = ROOT / "runs" / f"agent-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    logdir.mkdir(parents=True)
    print(f"[agent] 목표: {goal.strip().splitlines()[0]}")
    print(f"[agent] 작업 폴더: {WORKSPACE} / 로그: {logdir} / 승인: {APPROVAL}")

    pw = sync_playwright().start()
    proc = None
    try:
        browser, proc = ensure_browser(pw, site_url)
        page = get_page(browser, site, site_url)
        editor = wait_editor(page)
        print("[ready] 입력창 확인. 루프를 시작합니다.")

        msg = first_msg
        for step in range(1, MAX_STEPS + 1):
            (logdir / f"step-{step:02d}.request.txt").write_text(msg, encoding="utf-8")
            print(f"\n[step {step}/{MAX_STEPS}] 전송 → 응답 대기…", flush=True)
            baseline = reply_locator(page).count()
            send(page, editor, msg)
            reply = wait_response(page, baseline, RESPONSE_TIMEOUT)
            (logdir / f"step-{step:02d}.response.txt").write_text(reply, encoding="utf-8")

            actions, done = parse_actions(reply)
            if done:
                print(f"\n완료 — [DONE] 수신. 산출물: {WORKSPACE} / 로그: {logdir}")
                return
            if not actions:
                msg = (
                    "액션을 찾지 못했다. ```run 명령```, ```file 경로```, "
                    "또는 마지막 줄 [DONE] 형식으로만 답하라."
                )
                continue

            results = []
            for kind, arg, body in actions:
                results.append(run_shell(arg) if kind == "run"
                               else write_file_action(arg, body))
            (logdir / f"step-{step:02d}.result.txt").write_text(
                "\n\n".join(results), encoding="utf-8")
            msg = "[실행 결과]\n\n" + "\n\n".join(results)

        print(f"\n중단 — 최대 스텝({MAX_STEPS}) 도달. 로그: {logdir}")
        raise SystemExit(1)
    finally:
        pw.stop()
        if proc and os.getenv("AGENT_CLOSE_BROWSER") == "1":
            proc.terminate()


if __name__ == "__main__":
    main()
