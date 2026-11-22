#!/usr/bin/env bash
# 전용 프로필 + CDP 포트로 Chrome 실행 (macOS/Linux)
# 평소 쓰는 Chrome 프로필을 재사용하지 말 것. 포트는 외부에 공개하지 말 것.
set -euo pipefail

if [[ "$(uname)" == "Darwin" ]]; then
  CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else
  CHROME="${CHROME_BIN:-google-chrome}"
fi

exec "$CHROME" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir="${XDG_DATA_HOME:-$HOME/.local/share}/llm-cdp/profile-9222"
