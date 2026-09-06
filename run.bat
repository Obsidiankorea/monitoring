@echo off
rem 경남 기상 대시보드 - 한 번에 실행 (Windows)
rem
rem   탐색기: 더블클릭
rem   명령창: run.bat
rem
rem 처음 실행하면 가상환경을 만들고 의존성을 받는다(1~2분).
rem 두 번째부터는 바로 뜬다.

setlocal enabledelayedexpansion
cd /d "%~dp0"

if "%PORT%"=="" set PORT=8000
if "%HOST%"=="" set HOST=127.0.0.1
set PY=.venv\Scripts\python.exe

rem -- 1. 가상환경 --------------------------------------------------
if not exist "%PY%" (
  echo [*] 가상환경을 만듭니다
  python -m venv .venv
  if errorlevel 1 (
    echo [X] python 이 없습니다. https://www.python.org 에서 3.12 이상을 설치하고
    echo     설치 화면의 "Add python.exe to PATH" 를 체크하세요.
    pause & exit /b 1
  )
)

rem requirements.txt 가 더 새로우면 다시 설치한다
set NEED=0
if not exist ".venv\.installed" set NEED=1
if %NEED%==0 for /f %%i in ('powershell -NoProfile -Command ^
  "if((Get-Item requirements.txt).LastWriteTime -gt (Get-Item .venv\.installed).LastWriteTime){1}else{0}"') do set NEED=%%i
if "%NEED%"=="1" (
  echo [*] 의존성을 설치합니다 ^(처음 한 번, 1~2분^)
  "%PY%" -m pip install -q --upgrade pip
  "%PY%" -m pip install -q -r requirements.txt
  if errorlevel 1 ( echo [X] 설치 실패 & pause & exit /b 1 )
  echo. > .venv\.installed
)

rem -- 2. 기상청 키 -------------------------------------------------
rem 키는 저장소에 없다(.gitignore). 없으면 인수인계 묶음에서 가져온다.
if not exist "config\api_keys.txt" (
  if exist "handoff-mac\config\api_keys.txt" (
    if not exist config mkdir config
    copy /y "handoff-mac\config\api_keys.txt" "config\" >nul
    echo [*] 키 파일을 config\ 로 복사했습니다
  ) else (
    echo [X] config\api_keys.txt 가 없습니다. ORG_API_KEY 를 넣은 파일을 만드세요.
    pause & exit /b 1
  )
)

rem -- 3. 포트 ------------------------------------------------------
rem 이미 쓰고 있으면 다음 빈 포트를 찾는다. 수집기가 둘 돌면 API 호출이 두 배가 된다.
:findport
netstat -ano | findstr /r /c:"LISTENING" | findstr /c:":%PORT% " >nul
if not errorlevel 1 (
  echo [*] 포트 %PORT% 은 이미 사용 중입니다
  set /a PORT=%PORT%+1
  goto findport
)

set URL=http://localhost:%PORT%
echo [*] 서버를 띄웁니다 -^> %URL%
echo [*] 처음에는 자료를 받느라 화면이 채워지기까지 10~40초 걸립니다
echo.

rem 서버가 응답하면 브라우저를 연다
start "" /b powershell -NoProfile -Command ^
  "1..60 | %%{ Start-Sleep 1; try { Invoke-WebRequest -UseBasicParsing '%URL%/api/status' -TimeoutSec 2 | Out-Null; Start-Process '%URL%'; break } catch {} }"

rem -- 4. 서버 --------------------------------------------------------
rem 화면에서 [업데이트]로 새 코드를 받으면 서버가 종료 코드 42로 스스로 끝난다.
rem 그때만 다시 띄운다. 다른 코드로 끝나면(닫기·오류) 그대로 멈춘다 —
rem 오류로 죽는 서버를 무한히 되살리면 무엇이 잘못됐는지 알 수가 없다.
:runserver
"%PY%" -m app.main
if errorlevel 43 goto done
if errorlevel 42 (
  echo.
  echo [*] 업데이트를 반영해 다시 띄웁니다
  echo.
  goto runserver
)
:done
pause
