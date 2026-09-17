# 重启 DD 监控室客户端（无控制台方式，等同双击 run.cmd）。
#
# 先按命令行里的 main.py 找到正在跑的本项目实例并结束，再重新起一个，
# 这样改完代码不用手动关窗口、也不用担心起出两个实例。
#
#   pwsh -File dev\restart-client.ps1
#
# 参数：
#   -Console        带控制台启动（等同 run-console.cmd，能看取流/重连日志）
#   -NoWait         不等新进程窗口就绪，直接返回
param(
    [switch]$Console,
    [switch]$NoWait
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$main = Join-Path $repo 'main.py'
if (-not (Test-Path $main)) {
    throw "找不到 $main"
}

$venvPython = Join-Path $repo '.venv\Scripts\python.exe'
$venvPythonw = Join-Path $repo '.venv\Scripts\pythonw.exe'
$fallback = 'F:\CodexAppManager\Code\DD_Monitor-venv\Scripts'
if (-not (Test-Path $venvPython)) { $venvPython = Join-Path $fallback 'python.exe' }
if (-not (Test-Path $venvPythonw)) { $venvPythonw = Join-Path $fallback 'pythonw.exe' }

function Get-DdmProcesses {
    # 命令行里认「本项目目录 + main」：main.py 被引号或反斜杠包着的写法都要认出来
    # （只匹配 'main.py' 时漏掉过一个用别的方式启动的实例）
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object {
            $cmd = $_.CommandLine
            if (-not $cmd -or $cmd -notlike '*DD_Monitor_CE*') { return $false }
            $cmd -like '*main.py*' -or $cmd -like '*\main*'
        }
}

# ---- 1. 停掉正在跑的实例 ----
$running = @(Get-DdmProcesses)
if ($running.Count -gt 0) {
    Write-Host ("停止正在运行的实例：{0}" -f (($running | ForEach-Object { $_.ProcessId }) -join ', '))
    foreach ($proc in $running) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    # 等进程真的退出，否则紧接着启动会撞上单实例/文件锁
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-DdmProcesses).Count -eq 0) { break }
        Start-Sleep -Milliseconds 120
    }
    $left = @(Get-DdmProcesses)
    if ($left.Count -gt 0) {
        Write-Warning ("仍有 {0} 个进程没退出：{1}" -f $left.Count, (($left | ForEach-Object { $_.ProcessId }) -join ', '))
    }
} else {
    Write-Host '没有正在运行的实例。'
}

# ---- 2. 重新启动 ----
$exe = if ($Console) { $venvPython } else { $venvPythonw }
if (-not (Test-Path $exe)) { throw "找不到解释器 $exe" }

$env:PYTHON_VLC_LIB_PATH = Join-Path $repo 'libvlc.dll'
$env:PYTHONIOENCODING = 'utf-8'

if ($Console) {
    Write-Host "启动（带控制台）：$exe $main"
    & $exe $main
    exit $LASTEXITCODE
}

$proc = Start-Process -FilePath $exe -ArgumentList @($main) -WorkingDirectory $repo -PassThru
Write-Host ("已启动：PID {0}（{1}）" -f $proc.Id, (Split-Path -Leaf $exe))

if (-not $NoWait) {
    # 等主窗口出现；Python 起窗口要一会儿，超时就当它还在起
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
        $proc.Refresh()
        if ($proc.HasExited) {
            throw ("客户端启动后立刻退出了，退出码 {0}。用 -Console 跑一次看报错。" -f $proc.ExitCode)
        }
        if ($proc.MainWindowHandle -ne 0) {
            Write-Host '客户端窗口已就绪。'
            break
        }
    }
}
