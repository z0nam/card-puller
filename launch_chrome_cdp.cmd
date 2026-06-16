@echo off
rem launch_chrome_cdp.cmd - 카드사 attach 용 크롬을 디버깅 포트(9222) + 전용 프로필로 띄운다 (Windows).
rem 자동 로그인은 하지 않는다 - 이 크롬에서 사람이 직접 로그인한다 (launch_chrome_cdp.sh 의 Windows 판).
rem 사용: launch_chrome_cdp.cmd [열고싶은_URL]
setlocal

set "PORT=9222"
set "PROFILE=%USERPROFILE%\chrome-cdp-profile"
set "URL=%~1"
if "%URL%"=="" set "URL=https://www.hyundaicard.com"

rem 표준 설치 위치 3곳을 순서대로 탐색 (paren 블록을 피해 (x86) 경로 파싱 문제를 회피).
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME (
  echo [card-puller] Chrome not found in standard install locations.>&2
  echo [card-puller] Pass the chrome.exe path manually, or install Google Chrome.>&2
  exit /b 1
)

echo [card-puller] Launching Chrome on debug port %PORT%
echo [card-puller] profile: %PROFILE%
echo.
echo   1^) Log in to your card site MANUALLY in the Chrome window that opens.
echo   2^) Then, in another terminal:  .\card check
echo      ^(or: .\card pull 202605  /  .\card evidence 202605^)
echo.

start "card-puller-cdp" "%CHROME%" --remote-debugging-port=%PORT% --user-data-dir="%PROFILE%" "%URL%"
endlocal
