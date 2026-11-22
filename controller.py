#!/usr/bin/env python3
"""
controller.py — 로그인된 웹 LLM을 조작해 ZIP 프로젝트를 받아 검증하는 루프 컨트롤러.

흐름:
  1) 목적(goal.txt) + 규칙(prompt.txt) + 직전 검증 결과를 프롬프트로 전송
  2) 이번 회차 이름과 일치하는 ZIP 첨부를 다운로드
  3) runs/<작업ID>/<회차>/project/ 에 검증 후 압축 해제
  4) 로컬 Docker(기본) 또는 로컬 Python(RUNNER=local, 테스트 전용)에서 main.py 실행
  5) 완료 기준(cases/)과 비교
     - 합격 → ZIP, 소스, 실행 결과 경로 출력 후 종료
     - 실패 → 오류 요약을 같은 대화에 보내 전체 ZIP 재생성 요청
  6) 최대 회차 초과 또는 로그인·UI 문제 → 중단

사용 전 반드시 README.md의 "자동화가 허용되는 서비스" 및 보안 주의사항을 확인할 것.
"""

import json
import os
import re
import stat
import subprocess as sp
import sys
import uuid
import zipfile
import zlib
from pathlib import Path
from string import Template
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import load_config

load_config()  # config.env 값을 환경변수 기본값으로 적용

ROOT = Path(__file__).resolve().parent
IMAGE = os.getenv("JOB_IMAGE", "python:3.12-slim")
FILES = {"main.py", "logic.py", "README.md"}
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "4"))
RUNNER = os.getenv("RUNNER", "docker")  # docker(기본, 격리 실행) | local(테스트 전용, 비격리)

MAX_ZIP_BYTES = 2_000_000
MAX_FILE_BYTES = 512_000
MAX_LOG_BYTES = 65_536
RUN_TIMEOUT = 30  # 생성 프로젝트 1회 실행 제한(초)
REPLY_TIMEOUT_MS = 240_000


def read(path):
    return path.read_text(encoding="utf-8-sig")


def env_required(name):
    try:
        return os.environ[name]
    except KeyError:
        raise SystemExit(f"환경변수 {name} 가 필요합니다. README.md의 환경변수 표를 참고하세요.")


def origin(url):
    u = urlsplit(url)
    return u.scheme.lower(), u.netloc.lower()


# ---------------------------------------------------------------------------
# 1단계: 웹 LLM 조작 (서비스별 UI 차이는 주로 이 함수에 한정된다)
# ---------------------------------------------------------------------------
def ask_for_zip(page, message, name, dest, trusted_origins):
    editor = page.locator(env_required("EDITOR_CSS"))
    editor.fill(message)
    if send_css := os.getenv("SEND_CSS"):
        page.locator(send_css).click()
    else:
        editor.press("Enter")

    replies = page.locator(env_required("REPLY_CSS"))
    attachment = replies.get_by_role(
        os.getenv("ZIP_ROLE", "link"), name=name, exact=True
    ).last
    attachment.wait_for(state="visible", timeout=REPLY_TIMEOUT_MS)

    def trusted(ref):
        if ref == f"sandbox:/mnt/data/{name}":  # 일부 서비스의 내부 첨부 링크
            return True
        url = urljoin(page.url, ref).removeprefix("blob:")
        return origin(url) in trusted_origins

    href = attachment.get_attribute("href")
    if href and not trusted(href):
        raise SystemExit("중단: 승인된 첨부 출처가 아닙니다.")

    # 클릭 전에 이벤트 대기를 시작해야 빠른 다운로드도 놓치지 않는다.
    with page.expect_download(timeout=45_000) as event:
        attachment.click()
    download = event.value
    if not trusted(download.url):
        download.cancel()
        raise SystemExit("중단: 다운로드 출처를 확인하세요.")
    download.save_as(str(dest))


# ---------------------------------------------------------------------------
# 2단계: ZIP 검증 및 안전한 압축 해제
# ---------------------------------------------------------------------------
class BundleError(Exception):
    pass


def unpack(zip_path, dest):
    if zip_path.stat().st_size > MAX_ZIP_BYTES:
        raise BundleError("ZIP이 2 MB를 초과함")

    with zipfile.ZipFile(zip_path) as z:
        items = z.infolist()
        if len(items) != len(FILES) or {i.filename for i in items} != FILES:
            raise BundleError("ZIP 루트에는 main.py, logic.py, README.md만 있어야 함")

        dest.mkdir()
        for item in items:
            mode = stat.S_IFMT(item.external_attr >> 16)
            if (
                mode not in (0, stat.S_IFREG)
                or item.flag_bits & 1
                or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or item.file_size > MAX_FILE_BYTES
            ):
                raise BundleError("허용하지 않는 파일 종류, 압축 방식 또는 크기")
            with z.open(item) as f:
                data = f.read(MAX_FILE_BYTES + 1)
            if len(data) != item.file_size:
                raise BundleError("ZIP 파일 크기 불일치")
            # extractall 대신 검사된 고정 이름으로 새 일반 파일을 쓴다.
            (dest / item.filename).write_bytes(data)


# ---------------------------------------------------------------------------
# 3단계: 실행 (docker = 격리 기본값, local = 테스트 전용 비격리)
# ---------------------------------------------------------------------------
def docker(*args, seconds=25):
    return sp.run(
        ["docker", *args], check=True, capture_output=True,
        stdin=sp.DEVNULL, timeout=seconds,
    )


def run_docker(project, html):
    """네트워크 없는 읽기 전용 컨테이너에서 실행. (rc, stdout, stderr) 반환."""
    name = "llmjob-" + uuid.uuid4().hex
    try:
        docker(
            "run", "-d", "--name", name, "--pull=never",
            "--network=none", "--read-only", "--user=65534:65534",
            "--cap-drop=ALL", "--security-opt=no-new-privileges=true",
            "--memory=128m", "--memory-swap=128m", "--cpus=0.5", "--pids-limit=32",
            "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16m",
            "--log-driver=local", "--log-opt", "max-size=256k",
            "--log-opt", "max-file=1",
            "--mount", f"type=bind,src={project},dst=/app,readonly",
            "--mount", f"type=bind,src={html},dst=/input/page.html,readonly",
            "-w", "/app", IMAGE, "python", "-B", "-S", "/app/main.py",
        )
        try:
            rc = int(docker("wait", name, seconds=RUN_TIMEOUT + 5).stdout)
        except sp.TimeoutExpired:
            raise TimeoutError(f"실행 시간 {RUN_TIMEOUT}초 초과")
        log = docker("logs", name)
        return rc, log.stdout, log.stderr
    finally:
        sp.run(
            ["docker", "rm", "-f", name], stdout=sp.DEVNULL,
            stderr=sp.DEVNULL, timeout=15,
        )


def run_local(project, html):
    """테스트 전용 비격리 실행기.

    Docker 없는 환경에서 루프 자체를 검증하기 위한 것으로, 생성 코드가
    호스트에서 직접 실행된다. 신뢰할 수 있는 모의 ZIP으로만 사용할 것.
    입력 경로는 실행 계약의 PAGE_HTML 환경변수로 전달한다.
    """
    env = dict(os.environ)
    env["PAGE_HTML"] = str(html)
    env["PYTHONUTF8"] = "1"
    try:
        cp = sp.run(
            [sys.executable, "-B", "-S", str(project / "main.py")],
            cwd=project, env=env, stdin=sp.DEVNULL,
            capture_output=True, timeout=RUN_TIMEOUT,
        )
        return cp.returncode, cp.stdout, cp.stderr
    except sp.TimeoutExpired:
        raise TimeoutError(f"실행 시간 {RUN_TIMEOUT}초 초과")


# ---------------------------------------------------------------------------
# 4단계: 완료 판정 — 종료 코드 0은 목적 달성이 아니므로 출력 JSON까지 비교한다
# ---------------------------------------------------------------------------
_ERROR_KINDS = (
    "SyntaxError|IndentationError|NameError|ValueError|TypeError|"
    "KeyError|IndexError|AttributeError|ImportError|ModuleNotFoundError|"
    "FileNotFoundError|PermissionError|AssertionError|UnicodeDecodeError"
)


def canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


def judge(rc, stdout_b, stderr_b, expected):
    """통과면 None, 실패면 LLM에게 보낼 한 줄 요약(민감정보 제외)을 반환."""
    if len(stdout_b) + len(stderr_b) > MAX_LOG_BYTES:
        return "출력이 64 KiB를 초과함"
    if rc:
        # 원본 로그는 로컬에 남기고, 채팅에는 오류 종류와 소스 위치만 보낸다.
        err = stderr_b.decode("utf-8", "replace")
        frames = re.findall(r'File "[^"]*(main\.py|logic\.py)", line (\d{1,6})', err)
        kinds = re.findall(rf"(?m)^({_ERROR_KINDS})\b", err)
        loc = ":".join(frames[-1]) if frames else "위치 미상"
        return f"exit={rc}, {loc}, {kinds[-1] if kinds else '실행 실패'}"

    try:
        actual = json.loads(stdout_b.decode("utf-8"))
        if canonical(actual) == canonical(expected):
            return None
        if isinstance(actual, dict) and isinstance(expected, dict):
            wrong = [
                k for k in expected
                if k not in actual or canonical(actual[k]) != canonical(expected[k])
            ]
            if wrong:
                return "누락 또는 값이 잘못된 필드: " + ", ".join(wrong)[:120]
        return "출력 JSON 구조 또는 값이 완료 기준과 다름"
    except (ValueError, RecursionError):
        return "stdout이 유효한 UTF-8 JSON 하나가 아님"


def run_case(project, html, expected, round_dir, index):
    try:
        if RUNNER == "local":
            rc, out, err = run_local(project, html)
        else:
            rc, out, err = run_docker(project, html)
    except FileNotFoundError:
        raise SystemExit(
            "Docker 실행 파일을 찾을 수 없습니다. Docker를 설치하거나, "
            "테스트 목적이라면 RUNNER=local 로 실행하세요."
        )
    except sp.CalledProcessError as e:
        detail = (e.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise SystemExit(
            f"컨테이너 시작 실패: {detail}\n"
            f"'docker pull {IMAGE}' 완료 여부와 Docker 데몬 상태를 확인하세요."
        )
    except TimeoutError as e:
        return str(e)

    (round_dir / f"case-{index}.stdout.txt").write_bytes(out[:MAX_LOG_BYTES])
    (round_dir / f"case-{index}.stderr.txt").write_bytes(err[:MAX_LOG_BYTES])
    return judge(rc, out, err, expected)


# ---------------------------------------------------------------------------
# 메인 루프
# ---------------------------------------------------------------------------
def main():
    if RUNNER not in ("docker", "local"):
        raise SystemExit("RUNNER는 'docker' 또는 'local' 이어야 합니다.")
    if RUNNER == "local":
        print(
            "주의: RUNNER=local — 생성 코드가 격리 없이 이 PC에서 직접 실행됩니다. "
            "테스트 전용입니다.",
            flush=True,
        )

    port = int(os.getenv("CDP_PORT", "9222"))
    site = origin(env_required("LLM_ORIGIN"))
    trusted = {site} | {
        origin(s.strip()) for s in os.getenv("FILE_ORIGINS", "").split(",") if s.strip()
    }
    template = Template(read(ROOT / "prompt.txt"))
    goal = read(ROOT / "goal.txt")
    cases = [
        (html, json.loads(read(html.with_name("expected.json"))))
        for html in sorted(ROOT.glob("cases/*/page.html"))
    ]
    if not cases:
        raise SystemExit("cases/<번호>/page.html 및 expected.json이 필요합니다.")

    job = uuid.uuid4().hex[:10]
    feedback = "최초 회차. 목적을 분석하고 전체 프로젝트를 설계하라."

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        tabs = [
            p for ctx in browser.contexts for p in ctx.pages
            if origin(p.url) == site
        ]
        if len(tabs) != 1:
            raise SystemExit("전용 Chrome에 해당 웹 LLM 탭을 정확히 하나 열어주세요.")
        page = tabs[0]

        for n in range(1, MAX_ROUNDS + 1):
            if origin(page.url) != site:
                raise SystemExit("중단: 웹 LLM 탭의 출처가 변경되었습니다.")
            rd = ROOT / "runs" / job / f"{n:02d}"
            rd.mkdir(parents=True)
            name = f"project_{job}_{n:02d}.zip"
            msg = template.substitute(goal=goal, feedback=feedback, zipname=name)
            print(f"[{n}/{MAX_ROUNDS}] {name} 요청", flush=True)

            try:
                ask_for_zip(page, msg, name, rd / name, trusted)
            except PWTimeout:
                raise SystemExit(
                    "중단: 첨부를 확인하지 못했습니다. 로그인, 파일 생성 모드, "
                    "UI 선택자, 클릭 시 실제 다운로드가 발생하는지 확인하세요."
                )

            try:
                unpack(rd / name, rd / "project")
            except BundleError as e:
                feedback = f"패키징 오류: {e}"
            except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError):
                feedback = "읽을 수 없는 ZIP. 정상 ZIP으로 전체 프로젝트를 다시 생성하라."
            else:
                for i, (html, expected) in enumerate(cases, 1):
                    problem = run_case(rd / "project", html, expected, rd, i)
                    if problem:
                        feedback = f"검증 case-{i} 실패: {problem}"
                        break
                else:
                    print(f"PASS — ZIP, 소스, 실행 결과: {rd}")
                    return

            print(f"[{n}] {feedback}", flush=True)

    raise SystemExit(f"FAIL — {MAX_ROUNDS}회 안에 검증을 통과하지 못했습니다.")


if __name__ == "__main__":
    main()
