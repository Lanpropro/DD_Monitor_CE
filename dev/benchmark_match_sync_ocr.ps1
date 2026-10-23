# Optional Windows OCR feasibility probe. Runs outside the viewer; synthetic crops only.
param([Parameter(Mandatory=$true)][string]$ImageDirectory, [ValidateRange(1,1000)][int]$Repeats = 10)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
function Await-Result($Operation, [Type]$ResultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1
    } | Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$language = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]::new('en-US')
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
if ($null -eq $engine) { throw 'Windows English OCR is unavailable' }
$images = @()
foreach ($path in (Get-ChildItem -LiteralPath $ImageDirectory -Filter '*.png' | Sort-Object Name)) {
    $file = Await-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await-Result ($file.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
    try {
        $decoder = Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $images += @{ name = $path.BaseName; bitmap = $bitmap }
    } finally { $stream.Dispose() }
}
if ($images.Count -eq 0) { throw 'No timer crops supplied' }
$null = Await-Result ($engine.RecognizeAsync($images[0].bitmap)) ([Windows.Media.Ocr.OcrResult])
$timings = @()
$readings = @()
$cpuBefore = [System.Diagnostics.Process]::GetCurrentProcess().TotalProcessorTime.TotalMilliseconds
try {
    for ($round = 0; $round -lt $Repeats; $round++) {
        foreach ($item in $images) {
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            $result = Await-Result ($engine.RecognizeAsync($item.bitmap)) ([Windows.Media.Ocr.OcrResult])
            $timings += $watch.Elapsed.TotalMilliseconds
            if ($round -eq 0) { $readings += @{ fixture = $item.name; text = $result.Text.Trim() } }
        }
    }
    $process = [System.Diagnostics.Process]::GetCurrentProcess()
    $ordered = @($timings | Sort-Object)
    @{
        calls = $timings.Count
        average_ms = ($timings | Measure-Object -Average).Average
        p95_ms = $ordered[[Math]::Floor(($ordered.Count - 1) * .95)]
        cpu_ms_per_call = ($process.TotalProcessorTime.TotalMilliseconds - $cpuBefore) / $timings.Count
        worker_memory_mb = $process.WorkingSet64 / 1MB
        readings = $readings
    } | ConvertTo-Json -Depth 4
} finally {
    foreach ($item in $images) { $item.bitmap.Dispose() }
}
