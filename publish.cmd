@echo off
chcp 65001 >nul
rem 把当前内容提交并推送到 GitHub（改完代码后双击这个）
setlocal
cd /d "%~dp0"

echo === 当前改动 ===
git status --short
echo.
set /p msg=提交说明（直接回车用时间戳）: 
if "%msg%"=="" set "msg=更新 %date% %time%"

git add -A
git commit -m "%msg%"
git push
echo.
pause
