# 独立 WinForms EXE，只使用 Windows 自带的 .NET Framework，不依赖 Qt 或 Python。
param([string]$OutDir = "")
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $repo 'results\diagnostics' }
$OutDir = [IO.Path]::GetFullPath($OutDir)
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$compiler = Join-Path $env:SystemRoot 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '未找到 Windows .NET Framework C# 编译器。' }
$exe = Join-Path $OutDir 'DDMonitorDiagnostics.exe'
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ /utf8output "/out:$exe" `
    "/win32icon:$(Join-Path $repo 'favicon.ico')" `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Management.dll `
    /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll `
    (Join-Path $repo 'tools\diagnostics\Collector.cs') (Join-Path $repo 'tools\diagnostics\Program.cs')
if ($LASTEXITCODE -ne 0) { throw '诊断工具编译失败。' }
Copy-Item -LiteralPath (Join-Path $repo 'tools\diagnostics\README.md') -Destination (Join-Path $OutDir '使用说明.md') -Force
$zip = Join-Path $OutDir 'DDMonitorDiagnostics-v1.1.0.zip'
Compress-Archive -LiteralPath $exe,(Join-Path $OutDir '使用说明.md') -DestinationPath $zip -Force
Get-FileHash -LiteralPath $exe,$zip -Algorithm SHA256 | Format-Table -AutoSize
