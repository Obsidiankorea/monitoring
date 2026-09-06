@echo off
rem [!] 콘솔 코드페이지를 949 로 못 박는다. UTF-8(65001) 콘솔에서 부르면
rem     이 파일(CP949)이 깨져 보이고 파싱까지 어긋난다.
chcp 949 >nul

rem [!] 이 파일은 **CP949(ANSI/한국어)** 로 저장해야 한다. UTF-8 로 저장하면

rem     cmd 가 코드페이지 949 로 읽어 글자가 깨지고, 깨진 바이트가 파싱까지

rem     망가뜨려 중간에 멈춘다. 편집기에서 인코딩을 바꾸지 말 것.

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

rem -- 1. 업데이트 --------------------------------------------------
rem 저장소를 내려받아 쓰는 PC 에서만 동작한다. 새 버전이 있으면 물어본다.
rem
rem [!] 10초 안에 답이 없으면 **아니오**다. 벽면 PC 는 부팅하며 스스로 뜨는데,
rem     아무도 없는 새벽에 물음표에 걸려 화면이 안 뜨면 안 된다.
rem [!] 받기가 실패해도 멈추지 않는다. 지금 버전으로라도 뜨는 게 낫다.
rem [!] 의존성 설치보다 **먼저** 한다. requirements.txt 가 함께 바뀔 수 있어서,
rem     받은 뒤에 설치해야 새 목록이 반영된다.
where git >nul 2>&1
if errorlevel 1 goto skipupdate
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 goto skipupdate

rem 인터넷이 막힌 내부망에서 오래 매달리지 않게 - 8초간 느리면 포기한다
set GIT_HTTP_LOW_SPEED_LIMIT=1000
set GIT_HTTP_LOW_SPEED_TIME=8
set GIT_TERMINAL_PROMPT=0
echo [*] 새 버전이 있는지 확인합니다...
git fetch --quiet origin >nul 2>&1
if errorlevel 1 (
  echo [*] 확인하지 못했습니다 ^(인터넷이 막혔을 수 있습니다^). 그대로 실행합니다.
  goto skipupdate
)
set BEHIND=0
for /f %%i in ('git rev-list --count HEAD..@{u} 2^>nul') do set BEHIND=%%i
if "%BEHIND%"=="0" (
  echo [*] 최신입니다
  goto skipupdate
)
echo.
echo   ---- 새 버전 %BEHIND%개 ----------------------------------
rem [!] git 은 커밋 제목을 UTF-8 로 뱉는다. CP949 콘솔에 그대로 찍으면 깨진다.
rem     i18n.logOutputEncoding=cp949 는 제목에 CP949 에 없는 글자(em dash 등)가
rem     하나라도 있으면 그 줄을 통째로 포기한다. 그래서 파워셸로 읽어 바꿔 찍는다.
rem [!] 파워셸은 @{u} 를 해시테이블로 읽는다. 따옴표로 묶어야 git 까지 그대로 간다.
powershell -NoProfile -Command ^
  "$o=[Console]::OutputEncoding; [Console]::OutputEncoding=[Text.Encoding]::UTF8; $l=git --no-pager log --format='%%s' -5 'HEAD..@{u}'; [Console]::OutputEncoding=$o; $l | %%{ '   - ' + ($_ -replace '[\u2010-\u2015]','-') }"
echo   ---------------------------------------------------------
echo.
choice /C YN /T 10 /D N /M "  지금 받을까요 (Y/N, 10초 뒤 자동으로 N)"
if errorlevel 2 (
  echo [*] 받지 않고 실행합니다
  goto skipupdate
)
echo.
git pull --ff-only
if errorlevel 1 (
  echo.
  echo [X] 받지 못했습니다. 이 PC 에서 고친 파일이 새 버전과 겹칠 수 있습니다.
  echo     지금 버전 그대로 실행합니다.
  echo.
  timeout /t 5 >nul
) else (
  echo [*] 받았습니다
)
:skipupdate
echo.

rem -- 2. 가상환경 --------------------------------------------------
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

rem -- 3. 기상청 키 -------------------------------------------------
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

rem -- 4. 포트 ------------------------------------------------------
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

rem 서버가 응답하면 **웹앱 창**으로 연다 - 주소창/탭 없는 창(--app).
rem 상황실 화면이라 주소창이 보일 이유가 없고, 실수로 다른 데로 옮겨 가지도 않는다.
rem 창 아이콘은 화면의 파비콘(비바람)을 그대로 쓴다.
rem 크롬 -> 엣지 순으로 찾는다. 엣지는 윈도 10 에 늘 있으므로 사실상 항상 열린다.
rem 둘 다 없으면 기본 브라우저로 그냥 연다.
set "APPBROWSER="
for %%P in (
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
  "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
) do if not defined APPBROWSER if exist %%P set "APPBROWSER=%%~P"

if defined APPBROWSER (echo [*] 웹앱 창으로 엽니다) else (echo [*] 기본 브라우저로 엽니다)

rem [!] 뜨자마자 열면 흰 화면이 뜬다. /api/status 가 응답할 때까지 기다렸다 연다.
start "" /b powershell -NoProfile -Command ^
  "$b='%APPBROWSER%'; 1..90 | %%{ Start-Sleep 1; try { Invoke-WebRequest -UseBasicParsing '%URL%/api/status' -TimeoutSec 2 | Out-Null; if ($b) { Start-Process $b -ArgumentList '--app=%URL%','--window-size=1600,900' } else { Start-Process '%URL%' }; break } catch {} }"

rem -- 5. 서버 --------------------------------------------------------
rem 화면에서 [업데이트]로 새 코드를 받으면 서버가 종료 코드 42로 스스로 끝난다.
rem 그때만 다시 띄운다. 다른 코드로 끝나면(닫기·오류) 그대로 멈춘다 -
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
