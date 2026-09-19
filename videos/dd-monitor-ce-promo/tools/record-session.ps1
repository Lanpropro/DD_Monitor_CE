# 录屏会话工具 —— 为 DD监控室CE 宣传片抓真实软件画面
#
# 为什么需要它：
#   1. 屏幕是 3840x2160 而系统缩放是 150%，逻辑坐标和物理像素不是一回事，
#      手动把窗口摆到"逻辑 1920x1080"是对不准的，必须按物理像素算。
#   2. 录屏素材不可复现（直播间下播就补不回来），所以动作必须可脚本化、可重跑。
#
# 关键设计：
#   - 采集走 ddagrab（桌面复制 API）。它抓的是 DWM 合成之后的最终画面，
#     所以 libVLC 的 Direct3D 硬解画面能被正确抓到（GDI 的 BitBlt 会黑屏，不用它）。
#   - 母版固定抓**主显示器全屏 4K30**，成片时再按窗口区域裁切。
#     这样"拖窗口改方向"那一段（窗口会移动变形）也不会跑出画面。
#   - 程序改窗口尺寸 = 手动拖窗口：ddm/app.py:368 把方向切换挂在 resizeEvent 上，
#     判断条件只看窗口宽高，所以 SetWindowPos 触发的是同一条代码路径。

[CmdletBinding()]
param(
  [string]$OutFile = "raw\session.mp4",
  [string]$PlanFile,
  [int]$Fps = 30,
  [int]$LogicalWidth = 1920,
  [int]$LogicalHeight = 1080,
  [switch]$Launch,
  [switch]$ListOnly
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
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public const uint LEFTDOWN = 0x0002, LEFTUP = 0x0004;
  static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
  static readonly IntPtr HWND_NOTOPMOST = new IntPtr(-2);
  const uint SWP_NOMOVE = 0x0002, SWP_NOSIZE = 0x0001, SWP_SHOWWINDOW = 0x0040;
  // 置顶：SetForegroundWindow 对后台进程会被系统直接拒绝，
  // 所以先用 TOPMOST 把窗口抬起来再摘掉，这条路径稳定得多。
  public static void Front(IntPtr h) {
    ShowWindow(h, 9);
    SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
    SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
    SetForegroundWindow(h);
    System.Threading.Thread.Sleep(250);
  }
  public static void Click(int x, int y) {
    SetCursorPos(x, y);
    System.Threading.Thread.Sleep(90);
    mouse_event(LEFTDOWN, 0, 0, 0, IntPtr.Zero);
    System.Threading.Thread.Sleep(70);
    mouse_event(LEFTUP, 0, 0, 0, IntPtr.Zero);
  }
  public static string Rect(IntPtr h) {
    RECT r; GetWindowRect(h, out r);
    return string.Format("{0},{1} {2}x{3}", r.L, r.T, r.R - r.L, r.B - r.T);
  }
}
'@

# 让本进程按物理像素思考，否则 MoveWindow 的坐标会被系统按缩放再乘一遍
[void][Win]::SetProcessDpiAwarenessContext([IntPtr](-4))   # PER_MONITOR_AWARE_V2

# tools/ 往上是三层才是仓库根：tools -> dd-monitor-ce-promo -> videos -> 仓库根
$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$AppRoot = $RepoRoot
$Python = "F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\python.exe"
if (-not (Test-Path (Join-Path $AppRoot "main.py"))) { throw "仓库根判断错了：$AppRoot 下没有 main.py" }
if (-not (Test-Path $Python)) { throw "找不到虚拟环境的 python：$Python" }

function Get-AppWindow {
  Get-Process |
    Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -match 'DD' } |
    Select-Object -First 1
}

function Ensure-App {
  $p = Get-AppWindow
  if ($p) { Write-Host "已找到窗口：$($p.MainWindowTitle) (PID $($p.Id))"; return $p }
  if (-not $Launch) {
    throw "没找到 DD监控室CE 的窗口。加 -Launch 让脚本自己启动，或先手动打开。"
  }
  Write-Host "启动 DD监控室CE ..."
  Start-Process -FilePath $Python -ArgumentList "main.py" -WorkingDirectory $AppRoot
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $p = Get-AppWindow
    if ($p) { Write-Host "窗口起来了 (PID $($p.Id))"; Start-Sleep -Seconds 3; return $p }
  }
  throw "启动后 40 秒内没等到窗口"
}

# 系统缩放：物理像素 / 逻辑像素
$dpi = (Get-ItemProperty "HKCU:\Control Panel\Desktop\WindowMetrics" -ErrorAction SilentlyContinue).AppliedDPI
$scale = if ($dpi) { $dpi / 96.0 } else { 1.0 }
$physW = [int]($LogicalWidth * $scale)
$physH = [int]($LogicalHeight * $scale)

Write-Host "系统缩放 ${scale}x  ->  窗口物理尺寸 ${physW}x${physH} (逻辑 ${LogicalWidth}x${LogicalHeight})"

$proc = Ensure-App
$h = $proc.MainWindowHandle

if ($ListOnly) {
  Write-Host "当前窗口矩形：$([Win]::Rect($h))"
  exit 0
}

function Set-Window-Geometry([int]$lw, [int]$lh) {
  $w = [int]($lw * $scale); $hh = [int]($lh * $scale)
  [Win]::Front($h)          # 先置顶，否则后面 MoveWindow 摆好了也被别的窗口盖住
  [void][Win]::MoveWindow($h, 0, 0, $w, $hh, $true)
  [Win]::Front($h)
  Start-Sleep -Milliseconds 700
  Write-Host "  窗口 -> 逻辑 ${lw}x${lh}（物理 ${w}x${hh}）实际 $([Win]::Rect($h))"
}

function Invoke-Plan($plan) {
  $t0 = Get-Date
  foreach ($step in $plan) {
    $target = [double]$step.at
    $elapsed = ((Get-Date) - $t0).TotalSeconds
    if ($target -gt $elapsed) { Start-Sleep -Milliseconds ([int](($target - $elapsed) * 1000)) }
    switch ($step.type) {
      "resize" {
        Set-Window-Geometry ([int]$step.w) ([int]$step.h)
      }
      "click" {
        $r = New-Object Win+RECT
        [void][Win]::GetWindowRect($h, [ref]$r)
        [Win]::Click($r.L + [int]$step.x, $r.T + [int]$step.y)
        Write-Host "  [$([math]::Round($target,1))s] 点击窗口内 $($step.x),$($step.y)  ($($step.note))"
      }
      "key" {
        [void][Win]::SetForegroundWindow($h)
        [System.Windows.Forms.SendKeys]::SendWait($step.keys)
        Write-Host "  [$([math]::Round($target,1))s] 按键 $($step.keys)"
      }
      "wait" { }
      default { Write-Warning "未知动作类型：$($step.type)" }
    }
  }
}

# ---- 采集 ----
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
Write-Host "`n动作计划：$($plan.Count) 步，约 $planSeconds 秒，录制 $($planSeconds + $tail) 秒"

Set-Window-Geometry $LogicalWidth $LogicalHeight
Start-Sleep -Seconds 2

$recSecs = [int]([math]::Ceiling($planSeconds + $tail))
Write-Host "开始录制 -> $OutFile"
$ff = Start-Process -FilePath "ffmpeg" -PassThru -WindowStyle Hidden -ArgumentList @(
  "-hide_banner", "-loglevel", "warning", "-y",
  "-f", "lavfi", "-i", "ddagrab=framerate=$Fps",
  "-t", "$recSecs",
  "-vf", "hwdownload,format=bgra",
  "-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "21", "-pix_fmt", "yuv420p",
  $OutFile
)
Start-Sleep -Seconds 2
try {
  Invoke-Plan $plan
} finally {
  Write-Host "等待录制收尾 ..."
  $ff.WaitForExit(120000) | Out-Null
  if (-not $ff.HasExited) { $ff.Kill() }
}
Write-Host "`n完成：$OutFile"
if (Test-Path $OutFile) {
  $size = [math]::Round((Get-Item $OutFile).Length / 1MB, 1)
  Write-Host "体积 $size MB"
}
