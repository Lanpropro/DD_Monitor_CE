# 打出 DD 监控室 的发布包（Windows / PowerShell 5.1+）
#
#   powershell -File dev\build_release.ps1                 # 源码便携包（默认，已验证可用）
#   powershell -File dev\build_release.ps1 -OutDir D:\xx   # 换输出目录
#   powershell -File dev\build_release.ps1 -Frozen         # 另试：PyInstaller 免装 Python 版（见下）
#
# 默认产出 <OutDir>\DD监控室-v<版本>：
#   程序源码（ddm / blivedm / dev / docs / plugins_user）、启动脚本、
#   libVLC 运行库（libvlc.dll / libvlccore.dll / plugins）、许可证与运行说明，
#   再加上同名 .zip。**不含**用户的 utils\config.json、cache、logs。
#
# -Frozen 会额外尝试 PyInstaller 冻一个免装 Python 的 exe。注意：本机
#   PySide6 6.11 + PyInstaller 6.22 冻出来的 exe 目前**起不来**（Qt6Core.dll
#   加载失败；已确认不是文件缺失、也不是搜索路径问题，用干净的 Python 手动
#   add_dll_directory 加载同一批文件是成功的），所以这个开关默认关闭，而且
#   打开时会**实跑一次**，起不来就报错退出、不产出半成品。
param(
    [string]$OutDir = "",
    [switch]$SkipZip,
    [switch]$Frozen
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\python.exe"
}
if (-not (Test-Path $py)) { throw "没找到 Python 解释器（.venv 或 DD_Monitor-venv）" }

if (-not $OutDir) { $OutDir = Join-Path $repo "work\release" }
$OutDir = [System.IO.Path]::GetFullPath($OutDir)

$version = (& $py -c "import sys; sys.path.insert(0, r'$repo'); from ddm import version; print(version.VERSION_TAG)").Trim()
if (-not $version) { throw "读不到版本号（ddm/version.py）" }
$name = "DD监控室-$version"
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

# ---- 4) 可选：PyInstaller 免装 Python 版（默认关闭，见文件头说明）----
if ($Frozen) {
    Write-Output "=== -Frozen：试打 PyInstaller 版 ==="
    $build = Join-Path $repo "work\build"
    Remove-Item $build -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $build | Out-Null
    $frozenDir = Join-Path $OutDir "$name-frozen"
    & $py -m PyInstaller --noconfirm --clean --windowed --onedir --name "$name-frozen" `
        --icon (Join-Path $repo "favicon.ico") `
        --distpath $OutDir --workpath $build --specpath $build `
        --runtime-hook (Join-Path $repo "dev\pyi_rth_pyside6_paths.py") `
        (Join-Path $repo "main.py")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败（exit $LASTEXITCODE）" }
    $exe = Join-Path $frozenDir "$name-frozen.exe"
    Copy-Item (Join-Path $repo "libvlc.dll") $frozenDir -Force
    Copy-Item (Join-Path $repo "libvlccore.dll") $frozenDir -Force
    robocopy (Join-Path $repo "plugins") (Join-Path $frozenDir "plugins") /E /NFL /NDL /NJH /NJS /NP | Out-Null
    Write-Output "=== 实跑一次冻出来的 exe（起不来就报错）==="
    $proc = Start-Process -FilePath $exe -WorkingDirectory $frozenDir -PassThru
    Start-Sleep -Seconds 18
    if ($proc.HasExited) {
        throw "冻出来的 exe 起不来（exit $($proc.ExitCode)）—— 见文件头说明，别交付半成品"
    }
    Stop-Process -Id $proc.Id -Force
    Write-Output "  冻出来的 exe 能起来 ✓ -> $frozenDir"
}

if (-not $SkipZip) {
    $zip = Join-Path $OutDir "$name.zip"
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Write-Output "=== 压缩 $zip ==="
    Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal
}

$files = Get-ChildItem $app -Recurse -File
$size = ($files | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Output ("=== 完成：{0}（{1:N0} 个文件，{2:N1} MB）===" -f $app, $files.Count, $size)
