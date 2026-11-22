#!/usr/bin/env python3
"""
test_bat.py — .bat 파일 Windows 호환성 정적 검사.

cmd.exe는 배치 파일을 시스템 ANSI 코드페이지(한국어 Windows: CP949)로 읽는다.
따라서 실행되는 코드 라인은 ASCII만 허용하고, 한글은 REM 주석에만 둔다
(메모장에서는 UTF-8로 정상 표시되고, cmd는 REM 줄을 실행하지 않는다).
또한 cmd가 안정적으로 읽도록 CRLF 줄바꿈을 강제한다.

실행: python tests/test_bat.py
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKS = 0


def check(label, cond):
    global CHECKS
    assert cond, f"FAIL: {label}"
    CHECKS += 1
    print(f"  ok - {label}")


def lint_bat(path):
    raw = path.read_bytes()
    name = path.name

    # 1) 모든 줄바꿈이 CRLF인지
    check(
        f"{name}: 모든 줄바꿈이 CRLF",
        raw.count(b"\n") == raw.count(b"\r\n") > 0,
    )

    text = raw.decode("utf-8")
    lines = text.split("\r\n")

    # 2) 코드 라인은 ASCII만 (한글은 REM 주석에만 허용)
    bad = [
        (i, ln) for i, ln in enumerate(lines, 1)
        if ln.strip() and not re.match(r"(?i)rem\b", ln.strip()) and not ln.isascii()
    ]
    check(f"{name}: 실행 코드 전부 ASCII, 한글은 REM 주석만", not bad)

    # 3) if (...) 블록 안 echo 문의 괄호는 cmd 파서를 깨뜨림
    depth = 0
    offenders = []
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if depth > 0 and re.match(r"(?i)echo\b", s) and re.search(r"[()]", s):
            offenders.append((i, s))
        if s.endswith("("):
            depth += 1
        elif s.startswith(")"):
            depth = max(0, depth - 1)
    check(f"{name}: if 블록 내 echo 괄호 없음", not offenders)

    # 4) echo 문에 파이프/앰퍼샌드/리다이렉션 문자 없는지
    risky = [
        (i, ln) for i, ln in enumerate(lines, 1)
        if re.match(r"(?i)\s*echo\b", ln) and re.search(r"[&|<>]", ln)
    ]
    check(f"{name}: echo 특수문자(& | < >) 없음", not risky)

    # 5) 마지막이 pause인지 (더블클릭 실행 시 창 유지)
    last = next((ln.strip() for ln in reversed(lines) if ln.strip()), "")
    check(f"{name}: 마지막 명령 pause", last.lower() == "pause")


def main():
    bats = sorted(ROOT.glob("*.bat"))
    assert bats, "검사할 .bat 파일이 없습니다"
    for p in bats:
        lint_bat(p)
    print(f"\nPASS — bat {len(bats)}개 검사 통과 ({CHECKS}건)")


if __name__ == "__main__":
    main()
