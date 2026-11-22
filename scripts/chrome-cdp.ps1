# 전용 프로필 + CDP 포트로 Chrome 실행 (Windows PowerShell)
# 평소 쓰는 Chrome 프로필을 재사용하지 말 것. 포트는 외부에 공개하지 말 것.
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"

& $chrome `
  "--remote-debugging-address=127.0.0.1" `
  "--remote-debugging-port=9222" `
  "--user-data-dir=$env:LOCALAPPDATA\llm-cdp\profile-9222"
