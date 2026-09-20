# 录屏前后的配置准备 —— 让软件「开录时就是空墙 + 单画面」。
#
# 为什么不能靠动作计划里的鼠标操作：把 11 路从墙上清掉要么一格一格点关闭按钮，
# 要么右键每一格选「关闭这一路」，十几步里错一步这条长素材就废了。直接改配置
# 是确定的、可回滚的 —— 关注列表（32 个）原样保留，只把画面墙清空。
#
# 用法（改配置前必须先退出软件，否则它退出时会把旧状态写回去）：
#   powershell -File tools/prep-take.ps1 backup    # 备份当前配置到 raw/config-before-take.json
#   powershell -File tools/prep-take.ps1 empty     # 空墙 + 单画面（录制起点）
#   powershell -File tools/prep-take.ps1 restore   # 录完还原
#
# 本文件必须带 UTF-8 BOM，否则 PS 5.1 会按 ANSI 读成乱码。

[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [ValidateSet("backup", "empty", "restore", "show")]
  [string]$Action = "show"
)

$ErrorActionPreference = "Stop"

# tools -> dd-monitor-ce-promo -> videos -> 仓库根
$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$Config = Join-Path $RepoRoot "utils\config.json"
$Backup = Join-Path $PSScriptRoot "..\raw\config-before-take.json"

function Stop-App {
  $procs = Get-Process pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match 'DD' }
  foreach ($p in $procs) {
    Write-Host "关闭软件 (PID $($p.Id)) ..."
    $p.CloseMainWindow() | Out-Null
    if (-not $p.WaitForExit(8000)) { $p.Kill(); $p.WaitForExit(5000) | Out-Null }
  }
  Start-Sleep -Milliseconds 800
}

function Read-Config {
  if (-not (Test-Path $Config)) { throw "找不到配置：$Config" }
  Get-Content $Config -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-Config($state) {
  # 先留一份 .bak，和软件自己保存时的做法一致（ddm/config.py:save）
  Copy-Item -Force $Config ($Config + ".bak")
  $json = $state | ConvertTo-Json -Depth 12
  [System.IO.File]::WriteAllText($Config, $json, (New-Object System.Text.UTF8Encoding($false)))
  Write-Host "已写入 $Config"
}

switch ($Action) {
  "show" {
    $state = Read-Config
    Write-Host "关注 $($state.rooms.Count) 个；画面墙 $($state.wall.Count) 格"
    Write-Host "布局：横屏 $($state.ui.layout_landscape) / 竖屏 $($state.ui.layout_portrait)"
    Write-Host ("墙上：" + (($state.wall | ForEach-Object {
      if ($_.room_id) { $_.room_id } else { "(空)" } }) -join " "))
  }
  "backup" {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Backup) | Out-Null
    Copy-Item -Force $Config $Backup
    Write-Host "已备份配置 -> $Backup"
  }
  "empty" {
    Stop-App
    $state = Read-Config
    # 留一格空格子：1x1 布局下它就是「拖入直播间」的占位，正好当开场
    $state.wall = @([pscustomobject]@{
      room_id = ""; muted = $true; volume = 42; quality = 250; audio_channel = 0
    })
    $state.ui.layout_landscape = "1x1"
    $state.ui.layout_portrait = "portrait_main2"
    # 老配置里的 "layout" 键在启动时还会被当一次布局读（ddm/app.py:147），
    # 不改它的话起点会被它顶回上一次用的那套布局（实测：起点变成了 1+2）。
    $state.ui | Add-Member -Force -NotePropertyName layout -NotePropertyValue "1x1"
    Write-Config $state
    Write-Host "起点就绪：空墙 1 格 + 单画面布局，关注列表 $($state.rooms.Count) 个原样保留"
  }
  "restore" {
    Stop-App
    if (-not (Test-Path $Backup)) { throw "没有备份可还原：$Backup" }
    Copy-Item -Force $Backup $Config
    Write-Host "已还原配置（来自 $Backup）"
  }
}
