@echo off
REM ==== 전용 Chrome을 CDP 모드로 실행 ====
REM agent.py가 자동으로 띄우므로 보통은 필요 없습니다. 수동 실행용입니다.
cd /d "%~dp0"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo [ERROR] Chrome not found. Set CHROME_BIN in config.env instead.
  pause
  exit /b 1
)
start "" "%CHROME%" ^
  --remote-debugging-address=127.0.0.1 ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%LOCALAPPDATA%\llm-cdp\profile-9222" ^
  https://arena.ai/agent
echo Chrome started in CDP mode. Log in to Arena, then run run-agent.bat.
pause
