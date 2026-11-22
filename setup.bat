@echo off
REM ==== llm-loop 최초 1회 설치 스크립트 ====
REM 가상환경 생성 + 패키지 설치 + config.env 생성을 합니다.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install it from https://www.python.org/downloads/
  echo         and check "Add python.exe to PATH" during installation.
  pause
  exit /b 1
)
if not exist .venv (
  echo [1/3] Creating virtual environment...
  python -m venv .venv
)
echo [2/3] Installing packages...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Package installation failed.
  pause
  exit /b 1
)
if not exist config.env (
  copy config.env.example config.env >nul
  echo [3/3] config.env created. Open it with Notepad and check the values.
) else (
  echo [3/3] config.env already exists.
)
where docker >nul 2>nul
if errorlevel 1 (
  echo [NOTE] Docker not found. controller.py needs Docker Desktop,
  echo        or set RUNNER=local in config.env. agent.py works without Docker.
)
echo.
echo Setup complete. Next step: run-agent.bat
pause
