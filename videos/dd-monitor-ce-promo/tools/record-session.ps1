# 录屏会话工具 —— 为 DD监控室CE 宣传片抓真实软件画面 + 软件自己的声音
#
# 三个实测得来、必须遵守的点：
#
#  1) 缩放。屏幕 3840x2160 而系统缩放 150%，逻辑坐标和物理像素不是一回事。
#     本进程要声明 PER_MONITOR_AWARE_V2，再按物理像素摆窗口，否则对不准。
#     目标：逻辑 1920x1080 -> 物理 2880x1620 @ (0,0)。
#
#  2) 启动后有一次性延迟恢复。软件会把 config 里 saveGeometry 的最大化状态在启动几秒后
#     恢复回来，把刚摆好的尺寸顶掉（实测 3 秒后又变回 3862x2182）。所以要**等它恢复完
#     再摆**，并且摆完要循环校验。等够之后是稳定的（实测 20 秒不动）。
#
#  3) 采集。画面走 ddagrab（桌面复制 API）——它抓 DWM 合成后的最终画面，所以 libVLC 的
#     Direct3D 硬解直播能被正确抓到（GDI 的 BitBlt 会黑屏）。母版固定抓主显示器全屏 4K，
#     成片时再按窗口区域裁切，这样"拖窗口改方向"那段也不会跑出画面。
#     声音走 soundcard 的 WASAPI 回环：dshow 里没有回环设备（虚拟声卡端点被停用、
#     无管理员权限启用），回环抓的是默认输出设备上的混音——用户已把其他软件静音，
#     所以抓到的就是本软件自己的声音。
#
# 程序改窗口尺寸 = 手动拖窗口：ddm/app.py:368 把方向切换挂在 resizeEvent 上，
# 判断条件只看窗口宽高，所以 SetWindowPos 触发的是同一条代码路径。

[CmdletBinding()]
param(
  [string]$OutFile = "raw\session.mp4",
  [string]$PlanFile,
  [int]$Fps = 30,
  [int]$LogicalWidth = 1920,
  [int]$LogicalHeight = 1080,
  [switch]$Launch,
  [switch]$NoAudio,
  [switch]$DryRun,
  [string]$ShotsDir = "",
  [int]$LaunchSettleSeconds = 12
)

$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int hh, bool repaint);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public const uint LEFTDOWN = 0x0002, LEFTUP = 0x0004, RIGHTDOWN = 0x0008, RIGHTUP = 0x0010;
  static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
  static readonly IntPtr HWND_NOTOPMOST = new IntPtr(-2);
  const uint SWP_NOMOVE = 0x0002, SWP_NOSIZE = 0x0001, SWP_SHOWWINDOW = 0x0040;
  // SetForegroundWindow 对后台进程会被系统拒绝，先用 TOPMOST 抬起来再摘掉
  public static void Front(IntPtr h) {
    ShowWindow(h, 9);
    SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
    SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
    SetForegroundWindow(h);
    System.Threading.Thread.Sleep(250);
  }
  // 录制期间必须常驻置顶：否则桌面上别的窗口会盖住软件，
  // 而且模拟点击会落到那些窗口上（实测打偏过一次）。
  public static void KeepTopmost(IntPtr h) {
    SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
    SetForegroundWindow(h);
    System.Threading.Thread.Sleep(250);
  }
  // 只移动不改击 —— 关注列表的悬停预览要用它
  public static void Move(int x, int y) {
    SetCursorPos(x, y);
    System.Threading.Thread.Sleep(120);
  }
  public static void Click(int x, int y) {
    SetCursorPos(x, y);
    System.Threading.Thread.Sleep(90);
    mouse_event(LEFTDOWN, 0, 0, 0, IntPtr.Zero);
    System.Threading.Thread.Sleep(70);
    mouse_event(LEFTUP, 0, 0, 0, IntPtr.Zero);
  }
  // 右键：格子的音量 / 声道菜单、关注条目的「加入画面墙」都从这里出
  public static void RightClick(int x, int y) {
    SetCursorPos(x, y);
    System.Threading.Thread.Sleep(90);
    mouse_event(RIGHTDOWN, 0, 0, 0, IntPtr.Zero);
    System.Threading.Thread.Sleep(70);
    mouse_event(RIGHTUP, 0, 0, 0, IntPtr.Zero);
  }
  public static string Rect(IntPtr h) {
    RECT r; GetWindowRect(h, out r);
    return string.Format("{0}x{1}@{2},{3}", r.R - r.L, r.B - r.T, r.L, r.T);
  }
}
'@

[void][Win]::SetProcessDpiAwarenessContext([IntPtr](-4))   # PER_MONITOR_AWARE_V2

# tools/ 往上是三层才是仓库根：tools -> dd-monitor-ce-promo -> videos -> 仓库根
$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$AppRoot = $RepoRoot
$Python = "F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\python.exe"
$Loopback = Join-Path $PSScriptRoot "loopback-rec.py"
$MuteScript = Join-Path $PSScriptRoot "mute-app.py"
$LoopbackPy = "F:\CodexAppManager\Code\DD_Monitor_CE\work\musicgen-venv\Scripts\python.exe"
if (-not (Test-Path (Join-Path $AppRoot "main.py"))) { throw "仓库根判断错了：$AppRoot 下没有 main.py" }

function Get-AppWindow {
  Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -match 'DD' } | Select-Object -First 1
}

function Ensure-App {
  $p = Get-AppWindow
  if ($p) { Write-Host "已找到窗口：$($p.MainWindowTitle) (PID $($p.Id))"; return $p }
  if (-not $Launch) { throw "没找到 DD监控室CE 的窗口。加 -Launch 让脚本自己启动，或先手动打开。" }
  Write-Host "启动 DD监控室CE ..."
  Start-Process -FilePath $Python -ArgumentList "main.py" -WorkingDirectory $AppRoot
  $p = $null
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $p = Get-AppWindow
    if ($p) { break }
  }
  if (-not $p) { throw "启动后 20 秒内没等到窗口" }
  # 等它把 config 里存的（最大化）几何恢复完，否则摆好也会被顶掉
  Write-Host "  等窗口启动恢复完成（$LaunchSettleSeconds 秒）..."
  Start-Sleep -Seconds $LaunchSettleSeconds
  Write-Host "窗口就绪 (PID $($p.Id))"
  return (Get-AppWindow)
}

$dpi = (Get-ItemProperty "HKCU:\Control Panel\Desktop\WindowMetrics" -ErrorAction SilentlyContinue).AppliedDPI
$scale = if ($dpi) { $dpi / 96.0 } else { 1.0 }
$physW = [int]($LogicalWidth * $scale)
$physH = [int]($LogicalHeight * $scale)
Write-Host "系统缩放 ${scale}x  ->  窗口物理尺寸 ${physW}x${physH} (逻辑 ${LogicalWidth}x${LogicalHeight})"

$proc = Ensure-App
$h = $proc.MainWindowHandle

function Set-Window-Geometry([int]$lw, [int]$lh) {
  $w = [int]($lw * $scale); $hh = [int]($lh * $scale)
  $want = "${w}x${hh}@0,0"
  for ($i = 1; $i -le 6; $i++) {
    [Win]::Front($h)
    [void][Win]::MoveWindow($h, 0, 0, $w, $hh, $true)
    Start-Sleep -Milliseconds 800
    $now = [Win]::Rect($h)
    if ($now -like "${w}x${hh}@*") {
      Write-Host "  窗口 -> 逻辑 ${lw}x${lh}（物理 $want）OK"
      return
    }
  }
  throw "窗口摆到 $want 失败，当前 $([Win]::Rect($h))"
}

function Global-Point {
  <#
    把「窗口内坐标」换算成**屏幕坐标**。

    这套口径是实测钉下来的（tools/diagnose-clicks.py 用 QApplication.widgetAt
    反查过，别再凭直觉改）：

      · tools/measure-ui.py 量的「窗口内坐标」= Qt mapToGlobal 的差（客户区原点口径）
      · Qt 的 mapToGlobal 本身就给**屏幕物理像素**（本机缩放 150%，实测一致）
      · 点击用 GetWindowRect 的左上角 + 窗口内坐标，两者同口径，
        **不要再乘一次缩放** —— 乘了会整整偏 1.5 倍，表现是「动作都做了、
        一个都没点中」（这个坑踩了两轮，别再犯）。

    $Rect 是 GetWindowRect 给的物理矩形，$X/$Y 是窗口内坐标。
  #>
  param($Rect, [int]$X, [int]$Y)
  return @{ X = $Rect.L + $X; Y = $Rect.T + $Y }
}

function Invoke-MenuItem {
  <#
    右键出菜单 -> 先把光标移到某一项上（它可能是子菜单，展开要时间）-> 再点另一项。

    $Menu 里的偏移都是**相对窗口外框左上角**的逻辑坐标（见 tools/measure-ui.py
    量出来的 ui-metrics.json）：菜单弹在光标处，所以「右键点的位置 + 菜单项偏移」
    就是那一项在窗口里的位置。

    子菜单那一步用的是「相对父项中心」的偏移，因为光标这时正停在父项中心上。
  #>
  param($Step, $Rect)
  $menu = $Step.menu
  $base = Global-Point $Rect ([int]$Step.x) ([int]$Step.y)
  [Win]::RightClick($base.X, $base.Y)
  Start-Sleep -Milliseconds 450              # 等菜单画出来，太快会点空
  if ($menu.open) {
    $p = Global-Point $Rect ([int]$Step.x + [int]$menu.open.x) ([int]$Step.y + [int]$menu.open.y)
    [Win]::Move($p.X, $p.Y)
    Start-Sleep -Milliseconds 400
  }
  if ($menu.hover) {
    $p = Global-Point $Rect ([int]$Step.x + [int]$menu.hover.x) ([int]$Step.y + [int]$menu.hover.y)
    [Win]::Move($p.X, $p.Y)
    Start-Sleep -Milliseconds 500            # 子菜单展开
  }
  $target = Global-Point $Rect ([int]$Step.x + [int]$menu.item.x) ([int]$Step.y + [int]$menu.item.y)
  [Win]::Click($target.X, $target.Y)
  Start-Sleep -Milliseconds 250
  Write-Host ("  [{0,5:N1}s] 右键菜单：{1}  ->  窗口内 ({2},{3}) = 屏幕 ({4},{5})  {6}" -f `
      $Step.at, $menu.note, $menu.item.x, $menu.item.y, $target.X, $target.Y, $Step.note)
}

function Set-AppMute([string]$Action) {
  # 软件的画面墙格子显示「已静音」但实际仍出声，按进程静音才是真静音
  # （见 tools/mute-app.py 的说明）。录制期间要它安静 / 出声都走这里。
  if (-not (Test-Path $MuteScript)) { Write-Warning "找不到 mute-app.py，跳过静音切换"; return }
  & $LoopbackPy $MuteScript "python" $Action 2>$null | ForEach-Object { Write-Host "        $_" }
}

function Save-Shot([string]$Name, [string]$Rect) {
  # 干跑验证用：ffmpeg 抓桌面，再裁到指定区域。用于事后确认鼠标点到了哪。
  if (-not $ShotsDir) { return }
  New-Item -ItemType Directory -Force -Path $ShotsDir | Out-Null
  $out = Join-Path $ShotsDir "$Name.png"
  & ffmpeg -hide_banner -loglevel error -y -f gdigrab -i desktop `
    -vf "crop=$Rect" -frames:v 1 $out 2>$null
  Write-Host "        截图 -> $out"
}

function Invoke-Plan($plan, $Rect) {
  $t0 = Get-Date
  foreach ($step in $plan) {
    $target = [double]$step.at
    $elapsed = ((Get-Date) - $t0).TotalSeconds
    if ($target -gt $elapsed) { Start-Sleep -Milliseconds ([int](($target - $elapsed) * 1000)) }
    switch ($step.type) {
      "resize" {
        Set-Window-Geometry ([int]$step.w) ([int]$step.h)
        # Front() 结尾会摘掉 TOPMOST，拖完窗口就失去置顶、会被别的窗口盖住，补回来
        [Win]::KeepTopmost($h)
      }
      "click" {
        $r = New-Object Win+RECT
        [void][Win]::GetWindowRect($h, [ref]$r)
        $p = Global-Point $r ([int]$step.x) ([int]$step.y)
        [Win]::Click($p.X, $p.Y)
        Write-Host ("  [{0,5:N1}s] 点击窗口内 {1},{2}（屏幕 {3},{4}）  {5}" -f `
            $target, $step.x, $step.y, $p.X, $p.Y, $step.note)
      }
      "rightclick" {
        $r = New-Object Win+RECT
        [void][Win]::GetWindowRect($h, [ref]$r)
        Invoke-MenuItem $step $r
      }
      "key" {
        [void][Win]::SetForegroundWindow($h)
        [System.Windows.Forms.SendKeys]::SendWait($step.keys)
        Write-Host ("  [{0,5:N1}s] 按键 {1}  {2}" -f $target, $step.keys, $step.note)
      }
      "mute" {
        Set-AppMute $step.action
        Write-Host ("  [{0,5:N1}s] 软件音频 {1}  {2}" -f $target, $step.action, $step.note)
      }
      "maximize" {
        [Win]::ShowWindow($h, 3)
        Start-Sleep -Milliseconds 900
        [Win]::KeepTopmost($h)
        Write-Host ("  [{0,5:N1}s] 最大化  {1}" -f $target, $step.note)
      }
      "move" {
        $r = New-Object Win+RECT
        [void][Win]::GetWindowRect($h, [ref]$r)
        $p = Global-Point $r ([int]$step.x) ([int]$step.y)
        [Win]::Move($p.X, $p.Y)
        Write-Host ("  [{0,5:N1}s] 悬停 {1},{2}（屏幕 {3},{4}）  {5}" -f `
            $target, $step.x, $step.y, $p.X, $p.Y, $step.note)
      }
      "wait" { }
      default { Write-Warning "未知动作类型：$($step.type)" }
    }
    if ($ShotsDir -and $step.shot) {
      $r = New-Object Win+RECT
      [void][Win]::GetWindowRect($h, [ref]$r)
      $rect = if ($step.shot -is [string]) { $step.shot } else {
        "$($step.shot.w):$($step.shot.h):$($r.L + [int]$step.shot.x):$($r.T + [int]$step.shot.y)"
      }
      Save-Shot ("{0:d3}-{1}" -f [int]$target, ($step.type)) $rect
    }
  }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutFile) | Out-Null

if (-not $PlanFile) {
  Write-Host "`n没有给 -PlanFile，只摆好窗口并报告矩形。"
  Set-Window-Geometry $LogicalWidth $LogicalHeight
  exit 0
}

Add-Type -AssemblyName System.Windows.Forms
$plan = Get-Content $PlanFile -Raw -Encoding UTF8 | ConvertFrom-Json
$planSeconds = ($plan | Measure-Object -Property at -Maximum).Maximum
$tail = 4
$recSecs = [int]([math]::Ceiling($planSeconds + $tail))
Write-Host "`n动作计划：$($plan.Count) 步，约 $planSeconds 秒，录制 $recSecs 秒"

Set-Window-Geometry $LogicalWidth $LogicalHeight
[Win]::KeepTopmost($h)
Write-Host '  已常驻置顶（录制期间别的窗口不会盖上来）'
Start-Sleep -Seconds 2

if ($DryRun) {
  # 干跑：只走动作、不录画面也不录声音。用来先确认每个动作真的点在东西上
  # （配合 -ShotsDir 截图核对），确认完再走真录制 —— 长素材返工一次很贵。
  Write-Host "`n[干跑] 不录画面/声音，只走动作" -ForegroundColor Yellow
  $dryRect = New-Object Win+RECT
  [void][Win]::GetWindowRect($h, [ref]$dryRect)
  Invoke-Plan $plan $dryRect
  Write-Host "`n[干跑] 结束。窗口矩形 $([Win]::Rect($h))"
  exit 0
}

$dir = Split-Path -Parent $OutFile
$videoOnly = Join-Path $dir "session_video.mp4"
$audioWav = Join-Path $dir "session_audio.wav"

Write-Host "开始录制画面 -> $videoOnly"
$ff = Start-Process -FilePath "ffmpeg" -PassThru -WindowStyle Hidden -ArgumentList @(
  "-hide_banner", "-loglevel", "warning", "-y",
  "-f", "lavfi", "-i", "ddagrab=framerate=$Fps",
  "-t", "$recSecs",
  "-vf", "hwdownload,format=bgra",
  "-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "21", "-pix_fmt", "yuv420p",
  $videoOnly
)

$audioProc = $null
if (-not $NoAudio) {
  if ((Test-Path $LoopbackPy) -and (Test-Path $Loopback)) {
    Write-Host "同时录制软件声音（WASAPI 回环）-> $audioWav"
    $audioProc = Start-Process -FilePath $LoopbackPy -PassThru -WindowStyle Hidden `
      -ArgumentList @($Loopback, $audioWav, "$recSecs")
  } else {
    Write-Warning "找不到回环录音脚本，只录画面"
  }
}

Start-Sleep -Seconds 2
$recRect = New-Object Win+RECT
[void][Win]::GetWindowRect($h, [ref]$recRect)
try {
  Invoke-Plan $plan $recRect
} finally {
  Write-Host "等待录制收尾 ..."
  if ($audioProc -and -not $audioProc.HasExited) { $audioProc.WaitForExit(60000) | Out-Null }
  $ff.WaitForExit(120000) | Out-Null
  if (-not $ff.HasExited) { $ff.Kill() }
}

$hasAudio = (Test-Path $audioWav) -and ((Get-Item $audioWav -ErrorAction SilentlyContinue).Length -gt 4096)
if ($hasAudio) {
  Write-Host "合流画面与声音 -> $OutFile"
  & ffmpeg -hide_banner -loglevel error -y -i $videoOnly -i $audioWav -c:v copy -c:a aac -b:a 192k -shortest $OutFile
  if ($LASTEXITCODE -ne 0) { Write-Warning "合流失败，保留纯画面文件 $videoOnly" }
} else {
  Write-Warning "没有录到声音，输出纯画面"
  Copy-Item -Force $videoOnly $OutFile
}

if (Test-Path $OutFile) {
  $size = [math]::Round((Get-Item $OutFile).Length / 1MB, 1)
  Write-Host "`n完成：$OutFile  ($size MB)"
  & ffprobe -v error -show_entries stream=codec_type,codec_name -of csv=p=0 $OutFile | ForEach-Object { "  轨道: $_" }
}
