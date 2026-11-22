@echo off
REM ==== 에이전트 루프 실행 ====
REM 목표는 goal-agent.txt 를 메모장으로 편집해서 바꿉니다.
cd /d "%~dp0"
if not exist .venv (
  echo [ERROR] Run setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe agent.py %*
pause
