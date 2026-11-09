@echo off
setlocal
for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do call "%%i\VC\Auxiliary\Build\vcvars64.bat" >nul
where cl >nul 2>nul
if errorlevel 1 exit /b 1
if not exist work mkdir work
cl /nologo /LD /EHsc /O2 dev\checks\native_crash.cpp /Fework\check-native-crash.dll /Fowork\check-native-crash.obj /link dbghelp.lib
exit /b %errorlevel%
