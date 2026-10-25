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
# 开发入口与冻结包统一使用 PySide6 6.11.2，本机依赖位于 work\deps。
# 源码从当前 HEAD 导出，不打包未提交的本机文件。
param(
    [string]$OutDir = "",
    [string]$FFmpegExe = "",
    [string]$DependencyRoot = "",
    [switch]$SkipZip,
    [switch]$SourceOnly
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
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

# 录制是本体功能：发布包必须带一个可用的 FFmpeg，而不是让新用户填路径。
if (-not $FFmpegExe) {
    $bundled = Join-Path $repo "ffmpeg.exe"
    if (Test-Path $bundled) { $FFmpegExe = $bundled }
    else {
        $command = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
        if ($command) { $FFmpegExe = $command.Source }
    }
}
if (-not $FFmpegExe -or -not (Test-Path -LiteralPath $FFmpegExe -PathType Leaf)) {
    throw "找不到 ffmpeg.exe；请用 -FFmpegExe 指定打包机上的 FFmpeg 文件"
}
$FFmpegExe = [System.IO.Path]::GetFullPath($FFmpegExe)
$ffmpegHome = Split-Path (Split-Path $FFmpegExe -Parent) -Parent
$ffmpegLicense = Join-Path $ffmpegHome "LICENSE"
$ffmpegReadme = Join-Path $ffmpegHome "README.txt"
if (-not (Test-Path $ffmpegLicense) -or -not (Test-Path $ffmpegReadme)) {
    throw "FFmpeg 包缺少 LICENSE 或 README.txt，不能做发布包：$ffmpegHome"
}

if ((Split-Path $app -Parent) -ne $OutDir) { throw "源码包路径越界：$app" }
Remove-Item -LiteralPath $app -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $app | Out-Null

# ---- 1) 源码：**只打包 git 跟踪的文件** ----
# 不是简单拷目录：未跟踪的草稿/私有残留（比如 dev/mock_portrait.py 这种本地
# 试做文件）不能进发布包 —— 用户要求上传/发布前不能带他自己的测试数据。
& git -C $repo diff --quiet HEAD -- ddm blivedm assets main.py requirements.txt dev/build_release.ps1 dev/pyi_rth_pyside6_paths.py
if ($LASTEXITCODE -ne 0) { throw "请先提交开发源码，再从同一提交打包" }
$snapshot = Join-Path $OutDir "source-snapshot.zip"
& git -C $repo archive --format=zip --output=$snapshot HEAD
if ($LASTEXITCODE -ne 0) { throw "无法导出当前开发提交" }
$extractSource = @'
import fnmatch, sys, zipfile
excluded = ('plugins/*', 'plugins_user/*', 'utils/*', 'videos/*', 'dev/*promo*',
            'dev/*highlight*', 'dev/*videotogether*', 'docs/*VIDEO*', 'docs/*PROMO*', 'HANDOFF-*')
with zipfile.ZipFile(sys.argv[1]) as archive:
    for item in archive.infolist():
        if not any(fnmatch.fnmatchcase(item.filename, pattern) for pattern in excluded):
            archive.extract(item, sys.argv[2])
'@
& $py -c $extractSource $snapshot $app
if ($LASTEXITCODE -ne 0) { throw "开发源码导出失败" }
Remove-Item -LiteralPath $snapshot -Force
Copy-Item -LiteralPath $FFmpegExe -Destination (Join-Path $app "ffmpeg.exe") -Force
New-Item -ItemType Directory -Force -Path (Join-Path $app "ffmpeg-license") | Out-Null
Copy-Item -LiteralPath $ffmpegLicense -Destination (Join-Path $app "ffmpeg-license\LICENSE") -Force
Copy-Item -LiteralPath $ffmpegReadme -Destination (Join-Path $app "ffmpeg-license\README.txt") -Force

# ---- 2) libmpv 运行库（.gitignore 里不含它，得手动带上）----
$mpvSource = Get-Content -LiteralPath (Join-Path $repo "ddm\assets\licenses\libmpv-SOURCE.json") -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath (Join-Path $repo "libmpv-2.dll") -Algorithm SHA256).Hash.ToLower() -ne $mpvSource.dll_sha256) {
    throw "libmpv DLL 与固定来源的校验值不符，打包中止"
}
foreach ($file in @("libmpv-2.dll")) {
    $src = Join-Path $repo $file
    if (-not (Test-Path $src)) { throw "缺少 $file（libmpv 运行库），打包中止" }
    Copy-Item $src $app -Force
}
# 用户插件目录：直播平台扩展由独立插件仓库发布。
New-Item -ItemType Directory -Force -Path (Join-Path $app "plugins_user") | Out-Null
# utils is runtime user data; release packages start with an empty directory.
New-Item -ItemType Directory -Force -Path (Join-Path $app "utils") | Out-Null

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
libmpv-2.dll                libmpv 播放内核（必需，别删）
ffmpeg.exe                  录制与即时回放所用的 FFmpeg（自动发现，无需设置路径）
ffmpeg-license\             FFmpeg 的许可与来源说明
plugins_user\               插件目录（新插件含 plugin.json 和 plugin.py）
utils\                      配置目录（首次运行会生成 config.json）
docs\                       文档与截图
LICENSE / docs\NOTICE.md    许可与第三方声明
docs\releases\RELEASE-$version.md 这一版改了什么

说明
----
- 用的是 B 站的公开接口，需要联网。
- 删掉 utils\config.json 等于恢复出厂设置（关注列表、布局、音量都会重置）。
"@
Set-Content -Path (Join-Path $app "运行说明.txt") -Value $readme -Encoding UTF8

# ---- 4) exe 便携版（默认做；Q:\-SourceOnly 可跳过）----
if (-not $SourceOnly) {
    $deps = if ($DependencyRoot) { [System.IO.Path]::GetFullPath($DependencyRoot) } else { Join-Path $repo "work\deps" }
    if (-not (Test-Path (Join-Path $deps "PySide6"))) {
        throw @"
缺少 $deps（开发和冻结共用的 PySide6 6.11.2）。
安装命令：
    $py -m pip install --target "$deps" "PySide6==6.11.2"
"@
    }
    $env:PYTHONPATH = $deps
    $qtVersion = (& $py -c "from PySide6.QtCore import qVersion; print(qVersion())").Trim()
    if ($qtVersion -ne "6.11.2") { throw "开发与发布 Qt 版本必须一致：期望 6.11.2，实际 $qtVersion" }
    Write-Output "=== 冻 exe（PySide6 $qtVersion）==="
    $exeDir = Join-Path $OutDir $display
    $build = Join-Path $repo "work\exebuild"
    if ((Split-Path $exeDir -Parent) -ne $OutDir -or
        (Split-Path $build -Parent) -ne (Join-Path $repo "work")) { throw "构建目录路径越界" }
    Remove-Item -LiteralPath $exeDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $build -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $build | Out-Null
    $versionInfo = Join-Path $build "windows-version.txt"
    & $py (Join-Path $repo "dev\build_windows_version.py") $versionInfo
    if ($LASTEXITCODE -ne 0) { throw "Windows EXE 版本信息生成失败" }
    $env:PYTHONPATH = $deps
    # Dependency scanning must not pick same-named DLLs from unrelated PATH tools.
    $previousBuildPath = $env:PATH
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$(Split-Path -Parent $py)"
    try {
        & $py -m PyInstaller --noconfirm --clean --windowed --onedir --name $display `
        --icon (Join-Path $repo "favicon.ico") `
        --version-file $versionInfo `
        --distpath $OutDir --workpath $build --specpath $build `
        --runtime-hook (Join-Path $repo "dev\pyi_rth_pyside6_paths.py") `
        --collect-all streamlink `
        --collect-all pypinyin `
        --collect-all av `
        --hidden-import numpy `
        --hidden-import mpv `
        --copy-metadata python-mpv `
        --hidden-import ddm.live_danmaku `
        --hidden-import ddm.global_danmaku `
        --add-data ((Join-Path $repo "ddm\assets") + ";ddm\assets") `
        (Join-Path $repo "main.py")
        $freezeExit = $LASTEXITCODE
    } finally {
        $env:PATH = $previousBuildPath
    }
    if ($freezeExit -ne 0) { throw "PyInstaller 失败（exit $freezeExit）" }
    # 主程序名固定；带版本号的兼容入口供旧0.3更新器识别，启动后转到主程序。
    if ($version -eq "v0.3.1") {
        Copy-Item -LiteralPath (Join-Path $exeDir "$display.exe") -Destination (Join-Path $exeDir "$name.exe") -Force
    }
    @{ version = $version.TrimStart('v'); update_protocol = 1; platform = 'windows-x64' } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $exeDir "ddm-build.json") -Encoding UTF8
    # libmpv 与冻结后的 Python 模块放在同一个运行库目录。
    $internal = Join-Path $exeDir "_internal"
    Copy-Item -LiteralPath $FFmpegExe -Destination (Join-Path $exeDir "ffmpeg.exe") -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $exeDir "ffmpeg-license") | Out-Null
    Copy-Item -LiteralPath $ffmpegLicense -Destination (Join-Path $exeDir "ffmpeg-license\LICENSE") -Force
    Copy-Item -LiteralPath $ffmpegReadme -Destination (Join-Path $exeDir "ffmpeg-license\README.txt") -Force
    Copy-Item (Join-Path $repo "libmpv-2.dll") $internal -Force
    $mpvLicenseDir = Join-Path $exeDir "mpv-license"
    New-Item -ItemType Directory -Force -Path $mpvLicenseDir | Out-Null
    Get-ChildItem (Join-Path $repo "ddm\assets\licenses") -File |
        Where-Object { $_.Name -match '^(mpv-|python-mpv-|libmpv-)' } |
        Copy-Item -Destination $mpvLicenseDir -Force
    # 运行时侧栏会从 exe 同级 assets\logo.png 读取品牌图；favicon 也供 Qt 设置窗口图标。
    robocopy (Join-Path $repo "assets") (Join-Path $exeDir "assets") /E /NFL /NDL /NJH /NJS /NP | Out-Null
    # 用户插件目录：和源码便携包一样，独立发布的直播平台扩展不内置。
    # 用户自己的数据（plugins_user\_danmaku_log）照旧不带。
    New-Item -ItemType Directory -Force -Path (Join-Path $exeDir "plugins_user") | Out-Null
    foreach ($file in @("LICENSE", "docs/NOTICE.md", "docs/releases/RELEASE-v$($version.TrimStart('v')).md")) {
        $src = Join-Path $repo $file
        if (Test-Path $src) { Copy-Item $src $exeDir -Force }
    }
    $exeReadme = @"
DD 监控室 $version（exe 便携版）
================================

双击 $display.exe 启动。不需要装 Python。
配置 / 缓存 / 日志都在这个目录下（utils\config.json、cache\、logs\），
plugins_user\ 里是插件，可在设置页装载 ZIP 包，
整个目录拷到别的 Windows 10/11 64 位机器就能用。
_internal\ 里的东西（含 libmpv-2.dll）是运行库，别删。
ffmpeg.exe 用于录制和即时回放；ffmpeg-license\ 里有第三方许可与来源说明。
"@
    Set-Content -Path (Join-Path $exeDir "运行说明.txt") -Value $exeReadme -Encoding UTF8

    # 实跑验证：**看日志**，不看「进程还活着」——出错时 windowed 进程会弹框僵住，
    # 看起来也像活着，只有日志才说明真的进了 main()。
    Write-Output "=== 实跑 20 秒验证（看有没有写出启动日志）==="
    $logDir = Join-Path $exeDir "logs"
    Remove-Item $logDir -Recurse -Force -ErrorAction SilentlyContinue
    # 仅自检跳过首次须知，避免等待用户确认；配置不进入发布包。
    $testConfig = Join-Path $exeDir "utils\config.json"
    if (Test-Path -LiteralPath $testConfig) { throw "自检目录意外包含已有用户配置" }
    New-Item -ItemType Directory -Force -Path (Split-Path $testConfig -Parent) | Out-Null
    $probeJson = @{ version = 2; rooms = @(); wall = @(); user_notice_accepted = $true;
       plugins_enabled = @(); settings = @{ auto_update = $false } } |
        ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText($testConfig, $probeJson, (New-Object System.Text.UTF8Encoding($false)))
    $proc = Start-Process -FilePath (Join-Path $exeDir "$display.exe") -WorkingDirectory $exeDir -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 20
    $alive = -not $proc.HasExited
    if ($alive) { Stop-Process -Id $proc.Id -Force }
    # 等进程真的收工再往下走：句柄还开着的时候 Remove-Item 会静默失败，
    # 上一次就把验证用的 logs 留在了交付目录里（zip 里倒是干净的）。
    try { $null = $proc.WaitForExit(5000) } catch { }
    Start-Sleep -Milliseconds 300
    Remove-Item -LiteralPath $testConfig -Force
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
    # 验证时写出来的 logs / cache / 插件的运行目录不留在发布包里
    Remove-Item (Join-Path $exeDir "logs"), (Join-Path $exeDir "cache") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $exeDir "utils") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $exeDir "plugins_user\_danmaku_log") -Recurse -Force -ErrorAction SilentlyContinue
    & $py (Join-Path $repo "dev\build_program_inventory.py") --payload $exeDir
    if ($LASTEXITCODE -ne 0) { throw "程序文件清单生成失败" }
    # 再压一个 zip：用户要的就是「下载一个 zip、解压直接双击 exe 用」
    if (-not $SkipZip) {
        $exeZip = Join-Path $OutDir "$name-exe.zip"
        Remove-Item $exeZip -Force -ErrorAction SilentlyContinue
        Write-Output "=== 压缩 exe 包 $exeZip ==="
        Compress-Archive -Path $exeDir -DestinationPath $exeZip -CompressionLevel Optimal
        $releaseNotes = Join-Path $repo "docs/releases/RELEASE-$version.md"
        $updateNotes = if (Test-Path -LiteralPath $releaseNotes) { Get-Content -LiteralPath $releaseNotes -Raw -Encoding UTF8 } else { "" }
        $remoteExeName = "DDMonitorCE-$version-exe.zip"
        @{ version = $version.TrimStart('v'); asset_name = $remoteExeName;
           url = "https://github.com/Lanpropro/DD_Monitor_CE/releases/download/$version/$remoteExeName";
           sha256 = (Get-FileHash -LiteralPath $exeZip -Algorithm SHA256).Hash.ToLower();
           size = (Get-Item -LiteralPath $exeZip).Length; notes = [string]$updateNotes;
           release_url = "https://github.com/Lanpropro/DD_Monitor_CE/releases/tag/$version" } |
            ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $OutDir "app-update.json") -Encoding UTF8
        Write-Output ("  {0:N0} MB" -f ((Get-Item $exeZip).Length / 1MB))
    }
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
