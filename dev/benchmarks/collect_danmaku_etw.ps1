param(
    [Parameter(Mandatory = $true)][string]$OutputCsv,
    [ValidateSet('DDMDanmakuBench-20261024.exe')][string]$ProcessName = 'DDMDanmakuBench-20261024.exe',
    [ValidateRange(1, 86400)][int]$Seconds = 1800
)

$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$outputDirectory = [IO.Path]::GetFullPath((Join-Path $workspace 'work/danmaku-etw'))
$outputPath = [IO.Path]::GetFullPath($OutputCsv)
if ([IO.Path]::GetDirectoryName($outputPath) -ine $outputDirectory -or [IO.Path]::GetExtension($outputPath) -ine '.csv') {
    throw 'OutputCsv must be a new CSV directly inside this workspace work/danmaku-etw directory'
}
if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    throw 'Create work/danmaku-etw before starting the collector'
}
if ((Get-Item -LiteralPath $outputDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Collector output directory cannot be a junction or symlink'
}
$tool = Join-Path $workspace 'work/tools/PresentMon-2.6.0-x64.exe'
$expectedHash = 'b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af'
if ((Get-FileHash -LiteralPath $tool -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expectedHash) {
    throw 'PresentMon does not match the pinned official v2.6.0 SHA256'
}
$metadataPath = [IO.Path]::ChangeExtension($outputPath, '.collector.json')
$rawPath = [IO.Path]::ChangeExtension($outputPath, '.stdout.log')
$errorPath = [IO.Path]::ChangeExtension($outputPath, '.stderr.log')
foreach ($path in @($outputPath, $metadataPath, $rawPath, $errorPath)) {
    if (Test-Path -LiteralPath $path) { throw "Collector output already exists: $path" }
}
$csvStream = [IO.FileStream]::new($outputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
$csv = [IO.StreamWriter]::new($csvStream, [Text.UTF8Encoding]::new($false))
$csv.AutoFlush = $true
$rawStream = [IO.FileStream]::new($rawPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
$raw = [IO.StreamWriter]::new($rawStream, [Text.UTF8Encoding]::new($false))
$raw.AutoFlush = $true
$session = 'DDMonitor-Stdout-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $PID
$arguments = "--process_name $ProcessName --output_stdout --qpc_time --v2_metrics --write_display_metadata --timed $Seconds --terminate_after_timed --no_console_stats --session_name $session"
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $tool
$start.Arguments = $arguments
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$process = [Diagnostics.Process]::new()
$process.StartInfo = $start
$evidence = [ordered]@{
    status = 'starting'; collector_pid = $PID; presentmon_pid = $null
    process_name = $ProcessName; seconds = $Seconds; session_name = $session
    presentmon_path = $tool; presentmon_sha256 = $expectedHash
    collector_script_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    arguments = $arguments; output_csv = $outputPath; stdout_log = $rawPath; stderr_log = $errorPath
    qpc_frequency = [Diagnostics.Stopwatch]::Frequency
    startup_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
    rows = 0; ignored_stdout_lines = 0; exit_code = $null
}
$errorTask = $null
try {
    if (-not $process.Start()) { throw 'PresentMon failed to start' }
    $evidence.presentmon_pid = $process.Id
    $evidence.status = 'running'
    $evidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
    $errorTask = $process.StandardError.ReadToEndAsync()
    $headerSeen = $false
    while ($null -ne ($line = $process.StandardOutput.ReadLine())) {
        $raw.WriteLine($line)
        $clean = $line.TrimStart([char]0xFEFF)
        if ($clean.StartsWith('Application,ProcessID,SwapChainAddress,')) {
            if (-not $headerSeen) { $csv.WriteLine($clean); $headerSeen = $true }
        } elseif ($headerSeen -and $clean.StartsWith($ProcessName + ',')) {
            $csv.WriteLine($clean)
            $evidence.rows++
        } else {
            $evidence.ignored_stdout_lines++
        }
    }
    $process.WaitForExit()
    $evidence.exit_code = $process.ExitCode
    $evidence.status = if ($process.ExitCode -eq 0 -and $headerSeen) { 'complete' } else { 'failed' }
} catch {
    $evidence.status = 'failed'
    $evidence.error = $_.Exception.Message
    if ($evidence.presentmon_pid -and -not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
} finally {
    if ($errorTask) { [IO.File]::WriteAllText($errorPath, $errorTask.GetAwaiter().GetResult(), [Text.UTF8Encoding]::new($false)) }
    $csv.Dispose()
    $raw.Dispose()
    $evidence.end_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
    $evidence.csv_sha256 = (Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $evidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
    $process.Dispose()
}
if ($evidence.status -ne 'complete') { exit 1 }
