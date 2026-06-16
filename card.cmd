@echo off
rem card.cmd - card.py 를 프로젝트 venv 파이썬으로 실행하는 Windows 래퍼.
rem   card check | card pull [YYYYMM] | card evidence [YYYYMM]
rem POSIX ./card 와 동일한 역할. PATHEXT 에 .CMD 가 있어 `.\card check` 로 호출된다.
rem %~dp0 = 이 스크립트가 있는 폴더(끝에 \ 포함).
"%~dp0.venv\Scripts\python.exe" "%~dp0card.py" %*
exit /b %ERRORLEVEL%
