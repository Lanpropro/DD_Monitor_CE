# 打出 DD 监控室 的发布包（Windows / PowerShell 5.1+）
#
#   powershell -File dev\build_release.ps1                 # 默认输出到仓库里的 results\
#   powershell -File dev\build_release.ps1 -OutDir D:\xx   # 换输出目录
#   powershell -File dev\build_release.ps1 -SourceOnly     # 只要源码包，不冻 exe
#
# 默认产出（都落在 <OutDir>，默认就是仓库里的 results\）：
#   DD监控室-v<版本>-exe\   **免装 Python 的 exe 便携版**（双击 exe 即用）
#   DD监控室-v<版本>\       源码便携包（要 Python；-SourceOnly 时只出这个）
#   DD监控室-v<版本>.zip    源码包的压缩包
#
# exe 用 PyInstaller 冻结，但走**单独的依赖目录** `work\deps`（PySide6 6.9）：
#   主环境是 PySide6 6.11，冻出来的 exe 一 import QtCore 就报
#   「DLL load failed while importing QtCore」（文件不缺、路径也对，失败点在
#   Qt6Core.dll 自身加载）；6.9 的老布局没这个问题，程序在 6.9 下自查全过。
#   `work\deps` 缺了脚本会提示你怎么装（pip 要写系统临时目录，得在普通命令行跑）。
param(
    [string]$OutDir = "",
    [switch]$SkipZip,
    [switch]$SourceOnly
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\python.exe"
}
if (-not (Test-Path $py)) { throw "没找到 Python 解释器（.venv 或 DD_Monitor-venv）" }

if (-not $OutDir) { $OutDir = Join-Path $repo "results" }
$OutDir = [System.IO.Path]::GetFullPath($OutDir)

$version = (& $py -c "import sys; sys.path.insert(0, r'$repo'); from ddm import version; print(version.VERSION_TAG)").Trim()
if (-not $version) { throw "读不到版本号（ddm/version.py）" }
$display = (& $py -c "import sys; sys.path.insert(0, r'$repo'); from ddm import version; print(version.DISPLAY_NAME)").Trim()
if (-not $display) { $display = "DD监控室CE" }
$name = "$display-$version"
$app = Join-Path $OutDir $name
Write-Output "=== 打包 $name -> $OutDir ==="

Remove-Item $app -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $app | Out-Null

# ---- 1) 源码（不含用户数据、缓存、工作目录、虚拟环境）----
$skipDirs = @(".git", ".venv", "venv", "cache", "logs", "work", "results",
              "__pycache__", ".vscode", ".idea", "build", "dist")
foreach ($item in Get-ChildItem $repo -Force) {
    if ($skipDirs -contains $item.Name) { continue }
    if ($item.Name -in @("utils", "plugins")) { continue }   # 单独处理
    if ($item.PSIsContainer) {
        robocopy $item.FullName (Join-Path $app $item.Name) /E /XD __pycache__ .git /NFL /NDL /NJH /NJS /NP | Out-Null
    } else {
        Copy-Item $item.FullName $app -Force
    }
}

# ---- 2) VLC 运行库（.gitignore 里不含它，得手动带上）----
foreach ($file in @("libvlc.dll", "libvlccore.dll")) {
    $src = Join-Path $repo $file
    if (-not (Test-Path $src)) { throw "缺少 $file（VLC 运行库），打包中止" }
    Copy-Item $src $app -Force
}
robocopy (Join-Path $repo "plugins") (Join-Path $app "plugins") /E /NFL /NDL /NJH /NJS /NP | Out-Null
# 用户插件目录：带上模板和示例，别带用户自己的数据
New-Item -ItemType Directory -Force -Path (Join-Path $app "plugins_user") | Out-Null
foreach ($item in Get-ChildItem (Join-Path $repo "plugins_user") -Force -ErrorAction SilentlyContinue) {
    if ($item.Name -in @("_danmaku_log", "__pycache__")) { continue }
    if ($item.PSIsContainer) {
        robocopy $item.FullName (Join-Path $app "plugins_user\$($item.Name)") /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
    } else {
        Copy-Item $item.FullName (Join-Path $app "plugins_user") -Force
    }
}
# utils 目录只要代码；config.json 是用户数据，不带
New-Item -ItemType Directory -Force -Path (Join-Path $app "utils") | Out-Null
foreach ($item in Get-ChildItem (Join-Path $repo "utils") -Force -ErrorAction SilentlyContinue) {
    if ($item.Name -like "config.json*" -or $item.Name -eq "__pycache__") { continue }
    Copy-Item $item.FullName (Join-Path $app "utils") -Force -Recurse
}

# ---- 3) 运行说明 ----
$readme = @"
DD 监控室 $version（源码便携包）
==================================

运行
----
1) 装了 Python 3.12/3.13 的机器：在本目录执行一次
       python -m venv .venv
       .venv\Scripts\pip install -r requirements.txt
   然后双击 run.cmd 启动（run-console.cmd 带控制台看日志）。
2) 本机如果已经有现成的虚拟环境，run.cmd 会自己去
   F:\CodexAppManager\Code\DD_Monitor-venv 找解释器，直接双击即可。

目录说明
--------
main.py                     入口
ddm\                        程序本体
blivedm\                    弹幕库（B 站直播弹幕，随包提供）
dev\                        自检脚本与预览工具（改代码时用，运行程序不需要）
plugins\                    VLC 插件（必需，别删）
libvlc.dll / libvlccore.dll VLC 播放内核（必需，别删）
plugins_user\               插件目录（放 <名字>\plugin.py）
utils\                      配置目录（首次运行会生成 config.json）
docs\                       文档与截图
LICENSE / NOTICE.md         许可与第三方声明
RELEASE-$version.md         这一版改了什么

说明
----
- 用的是 B 站的公开接口，需要联网。
- 删掉 utils\config.json 等于恢复出厂设置（关注列表、布局、音量都会重置）。
"@
Set-Content -Path (Join-Path $app "运行说明.txt") -Value $readme -Encoding UTF8

# ---- 4) exe 便携版（默认做；Q:\-SourceOnly 可跳过）----
if (-not $SourceOnly) {
    $deps = Join-Path $repo "work\deps"
    if (-not (Test-Path (Join-Path $deps "PySide6"))) {
        throw @"
缺少 $deps（PySide6 6.9，冻结专用）。
先在**普通命令行**里执行一次（沙箱里 pip 写不了系统临时目录）：
    $py -m pip install --target "$deps" "PySide6==6.9.*"
为什么要单独装一份：主环境是 PySide6 6.11，冻出来的 exe 一 import QtCore 就报
「DLL load failed while importing QtCore」（文件不缺、路径也对，失败点在
Qt6Core.dll 自身加载）；6.9 的老布局没有这个问题，程序在 6.9 下自查全过。
"@
    }
    Write-Output "=== 冻 exe（PySide6 6.9）==="
    $exeDir = Join-Path $OutDir "$name-exe"
    $build = Join-Path $repo "work\exebuild"
    Remove-Item $exeDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $build -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $build | Out-Null
    $env:PYTHONPATH = $deps
    & $py -m PyInstaller --noconfirm --clean --windowed --onedir --name "$name-exe" `
        --icon (Join-Path $repo "favicon.ico") `
        --distpath $OutDir --workpath $build --specpath $build `
        --runtime-hook (Join-Path $repo "dev\pyi_rth_pyside6_paths.py") `
        (Join-Path $repo "main.py")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败（exit $LASTEXITCODE）" }
    # VLC 运行库要放 **_internal**（main.py 按 _MEIPASS 找 libvlc.dll，
    # 而 onedir 的 _MEIPASS 就是 _internal）；插件也必须和 dll 挨着
    $internal = Join-Path $exeDir "_internal"
    Copy-Item (Join-Path $repo "libvlc.dll") $internal -Force
    Copy-Item (Join-Path $repo "libvlccore.dll") $internal -Force
    robocopy (Join-Path $repo "plugins") (Join-Path $internal "plugins") /E /NFL /NDL /NJH /NJS /NP | Out-Null
    foreach ($file in @("LICENSE", "NOTICE.md", "RELEASE-v$($version.TrimStart('v')).md")) {
        $src = Join-Path $repo $file
        if (Test-Path $src) { Copy-Item $src $exeDir -Force }
    }
    $exeReadme = @"
DD 监控室 $version（exe 便携版）
================================

双击 DD监控室-$version-exe.exe 启动。不需要装 Python。
配置 / 缓存 / 日志都在这个目录下（utils\config.json、cache\、logs\），
整个目录拷到别的 Windows 10/11 64 位机器就能用。
_internal\ 里的东西（含 libvlc.dll 和 plugins\）是运行库，别删。
"@
    Set-Content -Path (Join-Path $exeDir "运行说明.txt") -Value $exeReadme -Encoding UTF8

    # 实跑验证：**看日志**，不看「进程还活着」——出错时 windowed 进程会弹框僵住，
    # 看起来也像活着，只有日志才说明真的进了 main()。
    Write-Output "=== 实跑 20 秒验证（看有没有写出启动日志）==="
    $logDir = Join-Path $exeDir "logs"
    Remove-Item $logDir -Recurse -Force -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath (Join-Path $exeDir "$name-exe.exe") -WorkingDirectory $exeDir -PassThru
    Start-Sleep -Seconds 20
    $alive = -not $proc.HasExited
    if ($alive) { Stop-Process -Id $proc.Id -Force }
    $log = Get-ChildItem $logDir -Filter "ddm-*.log" -ErrorAction SilentlyContinue | Select-Object -First 1
    $started = $false
    if ($log) {
        $started = [bool](Select-String -Path $log.FullName -Pattern '\[方向\]' -Quiet)
        Write-Output ("  日志：{0}" -f $log.Name)
    }
    if (-not $started) {
        throw "冻出来的 exe 没能启动（没写出 [方向] 启动日志）—— 别交付这半成品。日志目录：$logDir"
    }
    Write-Output "  exe 启动验证通过 ✓ -> $exeDir"
    # 验证时写出来的 logs / cache 不留在发布包里
    Remove-Item (Join-Path $exeDir "logs"), (Join-Path $exeDir "cache") -Recurse -Force -ErrorAction SilentlyContinue
    $exeFiles = Get-ChildItem $exeDir -Recurse -File
    Write-Output ("  exe 包：{0:N0} 个文件，{1:N0} MB" -f $exeFiles.Count,
                  (($exeFiles | Measure-Object Length -Sum).Sum / 1MB))
}

if (-not $SkipZip) {
    $zip = Join-Path $OutDir "$name.zip"
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Write-Output "=== 压缩 $zip ==="
    Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal
}

$files = Get-ChildItem $app -Recurse -File
$size = ($files | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Output ("=== 完成：源码包 {0}（{1:N0} 个文件，{2:N1} MB）===" -f $app, $files.Count, $size)
