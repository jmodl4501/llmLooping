#!/usr/bin/env python3
"""config.py — config.env 로더.

스크립트와 같은 폴더의 config.env를 읽어 환경변수로 적용한다.
이미 설정된 환경변수가 있으면 그 값이 우선한다(파일 값은 기본값 역할).
Windows 사용자는 config.env를 메모장으로 편집하면 된다.
"""

import os
from pathlib import Path


def load_config(path=None):
    p = Path(path) if path else Path(__file__).resolve().parent / "config.env"
    if not p.exists():
        return False
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)
    return True
