# 录一条连续长素材：视频（ffmpeg ddagrab）+ 软件声音（WASAPI 回环）+ 动作（进程内 Qt 事件）。
#
# 为什么动作不用系统鼠标：本环境实测 SetCursorPos + mouse_event 点不动窗口
# （见 tools/check-synth-input.py），必须在软件进程内打 Qt 事件
# （tools/drive-take.py，实测有效，见 tools/check-qt-inject.py）。
# record-session.ps1 里那套系统鼠标点击保留给"手动操作 + 只录"的场景。
#
# 用法（先跑 tools/prep-take.ps1 empty 把起点摆成空墙 + 单画面）：
#   powershell -File tools/shoot-take.ps1
#   powershell -File tools/shoot-take.ps1 -PlanFile tools/take-plan.json -OutFile raw/take.mp4
#
# 本文件必须带 UTF-8 BOM。

[CmdletBinding()]
param(
  [string]$PlanFile = "",
  [string]$OutFile = "",
  [int]$Fps = 30,
  [int]$Tail = 8,
  [switch]$KeepMuted          # 录完不还原音频会话（默认录完恢复静音状态）
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$Tools = $PSScriptRoot
$Promo = Split-Path -Parent $Tools
if (-not $PlanFile) { $PlanFile = Join-Path $Tools "take-plan.json" }
if (-not $OutFile) { $OutFile = Join-Path $Promo "raw\take.mp4" }
$Raw = Join-Path $Promo "raw"
$AppPy = "F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\python.exe"
$LoopbackPy = Join-Path $RepoRoot "work\musicgen-venv\Scripts\python.exe"
$Loopback = Join-Path $Tools "loopback-rec.py"
$MuteScript = Join-Path $Tools "mute-app.py"
$Drive = Join-Path $Tools "drive-take.py"
$Events = Join-Path $Raw "take-events.json"

if (-not (Test-Path $AppPy)) { throw "找不到软件用的 python：$AppPy" }
New-Item -ItemType Directory -Force -Path $Raw | Out-Null

# 计划总时长 + 尾巴，决定录多久
$plan = Get-Content $PlanFile -Raw -Encoding UTF8 | ConvertFrom-Json
$planSeconds = ($plan | Measure-Object -Property at -Maximum).Maximum
$lead = 3
$recSecs = [int][math]::Ceiling($planSeconds + $lead + $Tail)
Write-Host "动作计划：$($plan.Count) 步，$planSeconds 秒；录制 $recSecs 秒（含片头 $lead 秒 + 收尾 $Tail 秒）"

# 录之前先把软件按进程静音：它在"要出声"的那一拍由计划里的 mute 动作解开
if (Test-Path $MuteScript) {
  & $LoopbackPy $MuteScript "python" "mute" 2>$null | ForEach-Object { Write-Host "  $_" }
}

$videoOnly = Join-Path $Raw "take-video.mp4"
$audioWav = Join-Path $Raw "take-audio.wav"
Remove-Item -Force $videoOnly, $audioWav -ErrorAction SilentlyContinue

# 给用户 10 秒准备时间（用户要求：开始录之前要留准备时间）。
# 除了控制台倒计时，再弹一个不阻塞的提示窗口 —— 控制台不一定在眼前。
$countdown = 10
Write-Host "`n════════ 准备：$countdown 秒后开录，请现在停止操作鼠标键盘 ════════" -ForegroundColor Yellow
try {
  $shell = New-Object -ComObject WScript.Shell
  [void]$shell.Popup("录制将在 $countdown 秒后开始。`n请现在不要碰鼠标和键盘。",
                     $countdown, "DD监控室CE 宣传片 · 即将开录", 64)
} catch {
  for ($i = $countdown; $i -ge 1; $i--) {
    Write-Host ("  倒计时 {0,2} 秒" -f $i)
    Start-Sleep -Seconds 1
  }
}
Write-Host "════════ 开录 ════════`n" -ForegroundColor Green

Write-Host "开始录画面（ddagrab 主屏 4K$Fps）-> $videoOnly"
$ff = Start-Process -FilePath "ffmpeg" -PassThru -WindowStyle Hidden -ArgumentList @(
  "-hide_banner", "-loglevel", "warning", "-y",
  "-f", "lavfi", "-i", "ddagrab=framerate=$Fps",
  "-t", "$recSecs",
  "-vf", "hwdownload,format=bgra",
  "-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "21", "-pix_fmt", "yuv420p",
  $videoOnly
)

Write-Host "同时录软件声音（WASAPI 回环）-> $audioWav"
$audio = Start-Process -FilePath $LoopbackPy -PassThru -WindowStyle Hidden `
  -ArgumentList @("-u", $Loopback, $audioWav, "$recSecs")

Start-Sleep -Seconds 2

# 动作：进程内 Qt 事件驱动（它自己会等 --lead 秒再开始）
$driveArgs = @($Drive, "--plan", $PlanFile, "--mode", "picker",
               "--events", $Events, "--lead", "$lead")
$driver = Start-Process -FilePath $AppPy -PassThru -WindowStyle Hidden `
  -WorkingDirectory $RepoRoot -ArgumentList $driveArgs -RedirectStandardOutput (Join-Path $Raw "take-drive.log")

Write-Host "等动作驱动收尾 ..."
$driver.WaitForExit(600000) | Out-Null
if (-not $driver.HasExited) { $driver.Kill(); Write-Warning "动作驱动超时，已结束" }
Write-Host "  动作驱动退出码 $($driver.ExitCode)"
$AppPid = $driver.Id          # 驱动就是软件本体进程，按 PID 掐会话最准

foreach ($proc in @($audio, $ff)) {
  if ($proc -and -not $proc.HasExited) { $proc.WaitForExit(180000) | Out-Null }
  if ($proc -and -not $proc.HasExited) { $proc.Kill() }
}

$hasAudio = (Test-Path $audioWav) -and ((Get-Item $audioWav).Length -gt 4096)
if ($hasAudio) {
  Write-Host "合流画面与声音 -> $OutFile"
  & ffmpeg -hide_banner -loglevel error -y -i $videoOnly -i $audioWav `
    -c:v copy -c:a aac -b:a 192k -shortest $OutFile
  if ($LASTEXITCODE -ne 0) { Write-Warning "合流失败，保留纯画面 $videoOnly" }
} else {
  Write-Warning "没有录到声音，输出纯画面"
  Copy-Item -Force $videoOnly $OutFile
}

if (-not $KeepMuted -and (Test-Path $MuteScript)) {
  # 按 PID 收尾（按名字会命中这台机器上同时开着的其他 pythonw）
  & $LoopbackPy $MuteScript "pid:$AppPid" "mute" 2>$null |
    ForEach-Object { Write-Host "  $_" }
}

if (Test-Path $OutFile) {
  $size = [math]::Round((Get-Item $OutFile).Length / 1MB, 1)
  Write-Host "`n完成：$OutFile  ($size MB)"
  & ffprobe -v error -show_entries format=duration -show_entries stream=codec_type,codec_name `
    -of default=noprint_wrappers=1 $OutFile
  Write-Host "动作时刻表：$Events"
}
