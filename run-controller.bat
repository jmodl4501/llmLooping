@echo off
REM ==== ZIP 검증 루프 실행 (Docker Desktop 필요, 목표는 goal.txt 편집) ====
cd /d "%~dp0"
if not exist .venv (echo 먼저 setup.bat 을 실행하세요. & pause & exit /b 1)
where docker >nul 2>nul
if errorlevel 1 (
  echo [경고] Docker가 없습니다. config.env에서 RUNNER=local 로 바꾸거나 Docker Desktop을 설치하세요.
)
.venv\Scripts\python.exe controller.py %*
pause
