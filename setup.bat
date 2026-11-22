@echo off
REM ==== llm-loop 최초 1회 설치 ====
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [오류] Python이 필요합니다. https://www.python.org/downloads/ 에서 설치 시
  echo        "Add python.exe to PATH" 를 반드시 체크하세요.
  pause
  exit /b 1
)
if not exist .venv (
  echo [1/3] 가상환경 생성...
  python -m venv .venv
)
echo [2/3] 패키지 설치...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if not exist config.env (
  copy config.env.example config.env >nul
  echo [3/3] config.env 생성 완료 — 메모장으로 열어 값을 확인하세요.
) else (
  echo [3/3] config.env 이미 존재
)
where docker >nul 2>nul
if errorlevel 1 (
  echo [참고] Docker가 없습니다. controller.py^(ZIP 검증 루프^)를 쓰려면 Docker Desktop이,
  echo        없으면 config.env에서 RUNNER=local 로 바꾸세요. agent.py는 Docker 없이 동작합니다.
)
echo.
echo 설치 완료. 다음: start-chrome.bat 실행 후 run-agent.bat
pause
