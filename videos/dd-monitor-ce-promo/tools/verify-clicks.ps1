# 逐条验证动作计划的坐标：点一下、截一张图，给人眼确认。
#
# 为什么单开一个工具：动作计划里的坐标一旦打偏，录出来的长素材整条都废。
# 干跑（record-session.ps1 -DryRun）只走动作不录画面，但"点没点中"看不见 ——
# 这个脚本在每一步之后抓一张屏，落到 raw/verify/ 下，肉眼过一遍再开录。
#
# 用法：
#   powershell -File tools/verify-clicks.ps1 -PlanFile tools/dry-check-plan.json
#
# 本文件必须带 UTF-8 BOM。

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$PlanFile,
  [string]$OutDir = "",
  [int]$LogicalWidth = 1920,
  [int]$LogicalHeight = 1080,
  [switch]$Launch
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$Python = "F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\python.exe"
if (-not $OutDir) { $OutDir = Join-Path $RepoRoot "videos\dd-monitor-ce-promo\raw\verify" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class VWin {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out VRECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int hh, bool repaint);
  [StructLayout(LayoutKind.Sequential)] public struct VRECT { public int L, T, R, B; }
  public static void Click(int x, int y) {
    SetCursorPos(x, y);
    System.Threading.Thread.Sleep(90);
    mouse_event(0x0002, 0, 0, 0, IntPtr.Zero);
    System.Threading.Thread.Sleep(70);
    mouse_event(0x0004, 0, 0, 0, IntPtr.Zero);
  }
  public static void RightClick(int x, int y) {
    SetCursorPos(x, y);
    System.Threading.Thread.Sleep(90);
    mouse_event(0x0008, 0, 0, 0, IntPtr.Zero);
    System.Threading.Thread.Sleep(70);
    mouse_event(0x0010, 0, 0, 0, IntPtr.Zero);
  }
  public static void Move(int x, int y) { SetCursorPos(x, y); }
}
'@

[void][VWin]::SetProcessDpiAwarenessContext([IntPtr](-4))

function Get-AppWindow {
  Get-Process pythonw, python -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -match 'DD' } |
    Select-Object -First 1
}

if ($Launch) {
  $proc = Get-AppWindow
  if (-not $proc) {
    Write-Host "启动 DD监控室CE ..."
    Start-Process -FilePath $Python -ArgumentList "main.py" -WorkingDirectory $RepoRoot -WindowStyle Hidden
    for ($i = 0; $i -lt 40; $i++) {
      Start-Sleep -Milliseconds 500
      $proc = Get-AppWindow
      if ($proc) { break }
    }
  }
  if (-not $proc) { throw "没等到软件窗口" }
  Write-Host "等启动恢复完成（12 秒）..."
  Start-Sleep -Seconds 12
  $proc = Get-AppWindow
}

$h = $proc.MainWindowHandle
$rect = New-Object VWin+VRECT
[void][VWin]::GetWindowRect($h, [ref]$rect)
Write-Host "窗口矩形 $($rect.R - $rect.L)x$($rect.B - $rect.T)@$($rect.L),$($rect.T)"

# 必须把窗口摆成和探针量坐标时一样的尺寸：坐标是「窗口内相对坐标」，
# 窗口尺寸变了控件位置就变（侧栏跟着窗口高度走），量出来的数就不成立了。
$scale = 1.5
$wantW = [int]($LogicalWidth * $scale); $wantH = [int]($LogicalHeight * $scale)
for ($i = 1; $i -le 6; $i++) {
  [void][VWin]::MoveWindow($h, 0, 0, $wantW, $wantH, $true)
  Start-Sleep -Milliseconds 800
  [void][VWin]::GetWindowRect($h, [ref]$rect)
  if (($rect.R - $rect.L) -eq $wantW -and ($rect.B - $rect.T) -eq $wantH) { break }
}
Write-Host "摆到 ${wantW}x${wantH}@0,0 -> 现在 $($rect.R - $rect.L)x$($rect.B - $rect.T)@$($rect.L),$($rect.T)"
if (($rect.R - $rect.L) -ne $wantW -or ($rect.B - $rect.T) -ne $wantH) {
  throw "窗口没摆到目标尺寸，坐标验证没有意义，先解决这个"
}

function Shot([string]$Name) {
  $path = Join-Path $OutDir "$Name.png"
  $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
  $gfx = [System.Drawing.Graphics]::FromImage($bmp)
  $gfx.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bmp.Size)
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $gfx.Dispose(); $bmp.Dispose()
  Write-Host "  截图 -> $path"
}

$plan = Get-Content $PlanFile -Raw -Encoding UTF8 | ConvertFrom-Json

# 计划里的坐标是「窗口内坐标」（Qt 口径，物理像素），屏幕点 = 窗口外框左上角 + 它。
# **不要再乘缩放**：Qt 的 mapToGlobal 本身就是物理像素，乘了会偏 1.5 倍。
# 换算规则和真正播放的 record-session.ps1 的 Global-Point 完全一致。
function Screen-Point($Rect, [int]$X, [int]$Y) {
  return @{
    X = $Rect.L + $X
    Y = $Rect.T + $Y
  }
}

Shot "00-before"
$t0 = Get-Date
foreach ($step in $plan) {
  $target = [double]$step.at
  $elapsed = ((Get-Date) - $t0).TotalSeconds
  if ($target -gt $elapsed) { Start-Sleep -Milliseconds ([int](($target - $elapsed) * 1000)) }
  $r = New-Object VWin+VRECT
  [void][VWin]::GetWindowRect($h, [ref]$r)
  switch ($step.type) {
    "click" {
      $p = Screen-Point $r ([int]$step.x) ([int]$step.y)
      Shot ("{0:d3}-{1}-at-{2}x{3}" -f [int]$target, $step.type, $step.x, $step.y)
      [VWin]::Click($p.X, $p.Y)
      Start-Sleep -Milliseconds 400
      Shot ("{0:d3}-{1}-after-{2}x{3}" -f [int]$target, $step.type, $step.x, $step.y)
      Write-Host "  [$target s] 点击窗口内 $($step.x),$($step.y) = 屏幕 $($p.X),$($p.Y)  $($step.note)"
    }
    "move" {
      $p = Screen-Point $r ([int]$step.x) ([int]$step.y)
      [VWin]::Move($p.X, $p.Y)
      Start-Sleep -Milliseconds 300
      Shot ("{0:d3}-{1}-at-{2}x{3}" -f [int]$target, $step.type, $step.x, $step.y)
      Write-Host "  [$target s] 悬停 $($step.x),$($step.y) = 屏幕 $($p.X),$($p.Y)  $($step.note)"
    }
    "rightclick" {
      $p = Screen-Point $r ([int]$step.x) ([int]$step.y)
      [VWin]::Move($p.X, $p.Y)
      Start-Sleep -Milliseconds 200
      [VWin]::RightClick($p.X, $p.Y)
      Start-Sleep -Milliseconds 500
      Shot ("{0:d3}-{1}-menu-{2}x{3}" -f [int]$target, $step.type, $step.x, $step.y)
      $menu = $step.menu
      if ($menu.open) {
        $q = Screen-Point $r ([int]$step.x + [int]$menu.open.x) ([int]$step.y + [int]$menu.open.y)
        [VWin]::Move($q.X, $q.Y)
        Start-Sleep -Milliseconds 400
      }
      if ($menu.hover) {
        $q = Screen-Point $r ([int]$step.x + [int]$menu.hover.x) ([int]$step.y + [int]$menu.hover.y)
        [VWin]::Move($q.X, $q.Y)
        Start-Sleep -Milliseconds 600
        Shot ("{0:d3}-{1}-submenu" -f [int]$target, $step.type)
      }
      $q = Screen-Point $r ([int]$step.x + [int]$menu.item.x) ([int]$step.y + [int]$menu.item.y)
      [VWin]::Click($q.X, $q.Y)
      Start-Sleep -Milliseconds 500
      Shot ("{0:d3}-{1}-done" -f [int]$target, $step.type)
      Write-Host "  [$target s] 右键菜单 -> $($step.note)"
    }
    "resize" {
      [void][VWin]::MoveWindow($h, 0, 0, [int]([int]$step.w * $scale), [int]([int]$step.h * $scale), $true)
      Start-Sleep -Milliseconds 900
      Shot ("{0:d3}-{1}-{2}x{3}" -f [int]$target, $step.type, $step.w, $step.h)
      Write-Host "  [$target s] 摆窗口 $($step.w)x$($step.h)"
    }
    default { Write-Host "  [$target s] $($step.type)（本工具不执行）$($step.note)" }
  }
}
Shot "99-after"
Write-Host "`n截图都在 $OutDir"
