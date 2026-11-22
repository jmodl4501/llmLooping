#!/usr/bin/env python3
"""
mock_llm.py — 테스트용 모의 웹 LLM 서버.

실제 웹 LLM(ChatGPT 등)과 동일한 UI 계약을 흉내 낸다:
  - contenteditable 입력창(#prompt-textarea)에 Enter로 전송
  - assistant 답변 영역([data-message-author-role="assistant"])에
    요청받은 파일명과 정확히 일치하는 다운로드 링크를 생성

모드:
  fixable — 1회차는 검증에 실패하는 프로젝트, 2회차부터 수정된 프로젝트 제공
            (피드백 루프가 실제로 수정을 유도하는지 검증)
  broken  — 항상 실패하는 프로젝트 제공 (최대 회차 초과/중단 경로 검증)
  agent   — ZIP 대신 텍스트 액션(```file / ```run / [DONE])으로 응답하는
            에이전트 시나리오 (agent.py E2E 검증용)

제출된 프롬프트 전문은 server.submissions 에 기록되어 테스트가 검사할 수 있다.
"""

import io
import re
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>Mock LLM</title>
<style>
  body { font-family: sans-serif; max-width: 720px; margin: 2em auto; }
  #prompt-textarea { border: 1px solid #999; border-radius: 8px;
                     padding: 12px; min-height: 3em; }
  .reply { border-top: 1px solid #ddd; padding: 8px 0; }
</style></head>
<body>
<h1>Mock LLM</h1>
<div id="chat"></div>
<div id="prompt-textarea" contenteditable="true"></div>
<script>
const ta = document.getElementById('prompt-textarea');
function submit() {
  const text = ta.innerText || ta.textContent || '';
  fetch('/submit-log', {method: 'POST', body: text});
  const m = text.match(/project_[0-9a-z]+_\\d+\\.zip/);
  if (!m) return;
  const name = m[0];
  const reply = document.createElement('div');
  reply.className = 'reply';
  reply.setAttribute('data-message-author-role', 'assistant');
  const a = document.createElement('a');
  a.textContent = name;
  a.href = '/files/' + name;
  a.setAttribute('download', name);
  reply.appendChild(a);
  document.getElementById('chat').appendChild(reply);
}
ta.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
});
</script>
</body>
</html>
"""

# --- 1회차에 제공할 "일부러 틀린" 프로젝트: 엔티티 디코딩·공백 정규화 누락 ---
BAD_LOGIC = '''import re


def extract_title(html_text):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
    return m.group(1).strip() if m else ""
'''

# --- 2회차부터 제공할 "수정된" 프로젝트: goal.txt의 요구사항을 모두 충족 ---
GOOD_LOGIC = '''import re
from html.parser import HTMLParser

_WS = re.compile(r"\\s+")


class _TitleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._done = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "title" and not self._done:
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title = False
            self._done = True

    def handle_data(self, data):
        if self._in_title:
            self.parts.append(data)


def extract_title(html_text):
    parser = _TitleParser()
    parser.feed(html_text)
    parser.close()
    return _WS.sub(" ", "".join(parser.parts)).strip()
'''

MAIN = '''import json
import os
import sys
from pathlib import Path

from logic import extract_title


def main():
    src = Path(os.environ.get("PAGE_HTML", "/input/page.html"))
    try:
        html_text = src.read_text(encoding="utf-8")
    except OSError as e:
        print(f"입력 파일 오류: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"title": extract_title(html_text)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

README_BAD = "# mock project v1\n\n정규식 기반 title 추출(초안).\n"
README_GOOD = "# mock project v2\n\nhtml.parser 기반 추출. 엔티티 디코딩 + 공백 정규화 적용.\n"


# --- agent 모드: 플랫폼에 맞는 명령으로 응답하는 4스텝 시나리오 ---
# 1) 파일 작성 → 2) 실패하는 명령(오류 피드백 루프 검증) → 3) 성공 명령 → 4) [DONE]
_CAT = "type" if sys.platform == "win32" else "cat"
AGENT_SCENARIO = [
    "알겠습니다. 먼저 파일을 만듭니다.\n```file hello.txt\nhello arena agent\n```",
    f"이제 존재하지 않는 파일을 읽어 동작을 확인합니다.\n```run\n{_CAT} NOPE.txt\n```",
    f"오류를 확인했습니다. 이번에는 방금 만든 파일을 읽습니다.\n```run\n{_CAT} hello.txt\n```",
    "출력 내용을 확인했습니다. 목표를 달성했습니다.\n[DONE]",
]

AGENT_PAGE = """<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>Mock LLM (agent)</title>
<style>
  [data-message-author-role] { white-space: pre-wrap; border-top: 1px solid #ddd;
                               padding: 8px 0; }
  #prompt-textarea { border: 1px solid #999; border-radius: 8px;
                     padding: 12px; min-height: 3em; }
</style></head>
<body>
<h1>Mock LLM — agent</h1>
<div id="chat"></div>
<div id="prompt-textarea" contenteditable="true"></div>
<script>
const ta = document.getElementById('prompt-textarea');
async function submit() {
  const text = ta.innerText || ta.textContent || '';
  if (!text.trim()) return;
  fetch('/submit-log', {method: 'POST', body: text});
  const r = await fetch('/chat', {method: 'POST', body: text});
  const reply = await r.text();
  setTimeout(() => {
    const div = document.createElement('div');
    div.setAttribute('data-message-author-role', 'assistant');
    div.textContent = reply;
    document.getElementById('chat').appendChild(div);
  }, 400);
}
ta.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
});
</script>
</body>
</html>
"""


def build_zip(good):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("main.py", MAIN)
        z.writestr("logic.py", GOOD_LOGIC if good else BAD_LOGIC)
        z.writestr("README.md", README_GOOD if good else README_BAD)
    return buf.getvalue()


def create_server(mode="fixable", address=("127.0.0.1", 0)):
    if mode not in ("fixable", "broken", "agent"):
        raise ValueError(f"알 수 없는 모드: {mode}")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                page = AGENT_PAGE if mode == "agent" else PAGE
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            elif mode == "agent":
                self.send_error(404)
                return
            else:
                m = re.fullmatch(r"/files/(project_[0-9a-z]+_(\d+)\.zip)", self.path)
                if not m:
                    self.send_error(404)
                    return
                round_no = int(m.group(2))
                good = (mode == "fixable") and round_no >= 2
                body = build_zip(good)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{m.group(1)}"'
                )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            payload = self.rfile.read(length).decode("utf-8")
            if self.path == "/chat" and mode == "agent":
                n = self.server.chat_count
                self.server.chat_count += 1
                body = AGENT_SCENARIO[min(n, len(AGENT_SCENARIO) - 1)].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path != "/submit-log":
                self.send_error(404)
                return
            self.server.submissions.append(payload)
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass  # 테스트 출력 정리를 위해 access log 억제

    server = ThreadingHTTPServer(address, Handler)
    server.submissions = []
    server.chat_count = 0
    return server


if __name__ == "__main__":
    import sys
    import threading
    import webbrowser

    srv = create_server(sys.argv[1] if len(sys.argv) > 1 else "fixable")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"모의 LLM 서버: {url}  (Ctrl+C로 종료)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
