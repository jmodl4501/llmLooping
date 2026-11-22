@echo off
REM ==== ZIP 검증 루프 실행 ====
REM Docker Desktop이 필요합니다. 목표는 goal.txt, 완료 기준은 cases/ 를 편집합니다.
cd /d "%~dp0"
if not exist .venv (
  echo [ERROR] Run setup.bat first.
  pause
  exit /b 1
)
where docker >nul 2>nul
if errorlevel 1 (
  echo [WARN] Docker not found. Set RUNNER=local in config.env or install Docker Desktop.
)
.venv\Scripts\python.exe controller.py %*
pause
