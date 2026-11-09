@echo off
setlocal
for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do call "%%i\VC\Auxiliary\Build\vcvars64.bat" >nul
where cl >nul 2>nul
if errorlevel 1 exit /b 1
set "ddm_native_out=%~1"
if not defined ddm_native_out set "ddm_native_out=%~dp0..\work\native-diagnostics"
if not exist "%ddm_native_out%" mkdir "%ddm_native_out%"
cl /nologo /LD /MT /EHsc /O2 "%~dp0..\tools\native_diagnostics\capture.cpp" /Fe"%ddm_native_out%\DDMonitorNativeCapture.dll" /Fo"%ddm_native_out%\capture.obj" /link /INCREMENTAL:NO
if errorlevel 1 exit /b 1
cl /nologo /MT /EHsc /O2 /DDDM_WATCHER "%~dp0..\tools\native_diagnostics\capture.cpp" /Fe"%ddm_native_out%\DDMonitorCrashWatcher.exe" /Fo"%ddm_native_out%\watcher.obj" /link dbghelp.lib /INCREMENTAL:NO
exit /b %errorlevel%
