@echo off
REM ==== 전용 Chrome을 CDP 모드로 실행 (agent.py가 자동 실행하므로 선택 사항) ====
cd /d "%~dp0"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo [오류] Chrome을 찾을 수 없습니다.
  pause
  exit /b 1
)
start "" "%CHROME%" ^
  --remote-debugging-address=127.0.0.1 ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%LOCALAPPDATA%\llm-cdp\profile-9222" ^
  https://arena.ai/agent
echo Chrome이 CDP 모드로 실행되었습니다. Arena 로그인 후 run-agent.bat 을 실행하세요.
pause
