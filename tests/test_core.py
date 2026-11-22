#!/usr/bin/env python3
"""
test_core.py — unpack()/judge() 단위 테스트.

브라우저·Docker 없이 컨트롤러의 검증 로직만 검사한다.
실행: python tests/test_core.py
"""

import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controller import BundleError, judge, unpack  # noqa: E402

PASS = 0


def check(label, cond):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok - {label}")


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


GOOD = {"main.py": "print('hi')\n", "logic.py": "X = 1\n", "README.md": "# t\n"}


def test_unpack():
    print("[unpack]")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # 1) 정상 ZIP
        z = td / "ok.zip"
        z.write_bytes(make_zip(GOOD))
        unpack(z, td / "ok")
        check("정상 ZIP 해제", (td / "ok" / "main.py").read_text() == "print('hi')\n")

        # 2) 파일 누락
        z = td / "missing.zip"
        z.write_bytes(make_zip({"main.py": "x", "logic.py": "y"}))
        try:
            unpack(z, td / "m")
            check("누락 ZIP 거부", False)
        except BundleError:
            check("누락 ZIP 거부", True)

        # 3) 상위 폴더 포함
        z = td / "nested.zip"
        z.write_bytes(make_zip({f"pkg/{k}": v for k, v in GOOD.items()}))
        try:
            unpack(z, td / "n")
            check("중첩 ZIP 거부", False)
        except BundleError:
            check("중첩 ZIP 거부", True)

        # 4) 경로 탈출 시도 이름
        z = td / "evil.zip"
        z.write_bytes(make_zip({"../main.py": "x", "logic.py": "y", "README.md": "z"}))
        try:
            unpack(z, td / "e")
            check("경로 탈출 ZIP 거부", False)
        except BundleError:
            check("경로 탈출 ZIP 거부", True)

        # 5) 512 KB 초과 파일
        z = td / "big.zip"
        z.write_bytes(make_zip({**GOOD, "main.py": "A" * 512_001}))
        try:
            unpack(z, td / "b")
            check("대용량 파일 거부", False)
        except BundleError:
            check("대용량 파일 거부", True)

        # 6) 깨진 ZIP
        z = td / "broken.zip"
        z.write_bytes(b"not a zip")
        try:
            unpack(z, td / "x")
            check("손상 ZIP 예외", False)
        except zipfile.BadZipFile:
            check("손상 ZIP 예외", True)

        # 7) 2 MB 초과 ZIP 파일 자체
        z = td / "huge.zip"
        z.write_bytes(b"\0" * 2_000_001)
        try:
            unpack(z, td / "h")
            check("2MB 초과 ZIP 거부", False)
        except BundleError:
            check("2MB 초과 ZIP 거부", True)


def test_judge():
    print("[judge]")
    expected = {"title": "Demo & Docs"}
    check("정답 통과", judge(0, b'{"title":"Demo & Docs"}', b"", expected) is None)
    check("키 순서 무관", judge(0, b'{ "title" : "Demo & Docs" }', b"", expected) is None)
    r = judge(0, b'{"title":"wrong"}', b"", expected)
    check("잘못된 값 지적", r is not None and "title" in r)
    r = judge(0, b'{}', b"", expected)
    check("누락 필드 지적", r is not None and "title" in r)
    check("JSON 아님", judge(0, b"hello", b"", expected) is not None)
    tb = (
        b'Traceback (most recent call last):\n'
        b'  File "/app/main.py", line 9, in <module>\n'
        b"NameError: name 'x' is not defined\n"
    )
    r = judge(1, b"", tb, expected)
    check("런타임 오류 요약", r == "exit=1, main.py:9, NameError")
    check("출력 초과", judge(0, b"x" * 70_000, b"", expected) is not None)


if __name__ == "__main__":
    test_unpack()
    test_judge()
    print(f"\nPASS — 단위 테스트 {PASS}건 모두 통과")
