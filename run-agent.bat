@echo off
REM ==== 에이전트 루프 실행 (목표는 goal-agent.txt 편집) ====
cd /d "%~dp0"
if not exist .venv (echo 먼저 setup.bat 을 실행하세요. & pause & exit /b 1)
.venv\Scripts\python.exe agent.py %*
pause
