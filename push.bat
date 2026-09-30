@echo off
rem 바뀐 것을 모두 커밋하고 GitHub 에 올린다. 더블클릭해서 쓴다.
rem   메시지 창에서 그냥 Enter -> 메시지 없이 올린다 / 내용 치고 Enter -> 그대로 올린다
rem [!] 이 파일은 CP949 로 둔다(.gitattributes 참고). 실제 일은 tools\push.ps1 이 한다.
chcp 949 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\push.ps1"
echo.
pause
