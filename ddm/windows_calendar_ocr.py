"""Local Windows OCR for schedule images, including text positions."""
from base64 import b64encode
import os
from pathlib import Path

from PySide6.QtCore import QProcessEnvironment


_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
    $null = [Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType=WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
    $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapTransform, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1
    } | Select-Object -First 1
    function Wait-Result($operation, [Type]$resultType) {
        $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
        $task.Wait()
        $task.Result
    }
    $engines = @(
        foreach ($tag in 'zh-CN', 'en-US') {
            $language = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]::new($tag)
            $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
            if ($null -ne $engine) { $engine }
        }
    )
    if (-not $engines.Count) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
        if ($null -ne $engine) { $engines = @($engine) }
    }
    if (-not $engines.Count) { '{"error":"language"}'; exit }
    $file = Wait-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:DDM_CALENDAR_IMAGE)) ([Windows.Storage.StorageFile])
    $stream = Wait-Result ($file.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
    try {
        $decoder = Wait-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $limit = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension / [Math]::Max($decoder.OrientedPixelWidth, $decoder.OrientedPixelHeight)
        $scales = @([Math]::Min(1, $limit), [Math]::Min(2, $limit)) | Select-Object -Unique
        $passes = @(
            foreach ($scale in $scales) {
                $transform = [Windows.Graphics.Imaging.BitmapTransform]::new()
                $transform.ScaledWidth = [Math]::Max(1, [int]($scale * $decoder.PixelWidth))
                $transform.ScaledHeight = [Math]::Max(1, [int]($scale * $decoder.PixelHeight))
                $bitmap = Wait-Result ($decoder.GetSoftwareBitmapAsync(
                    [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
                    [Windows.Graphics.Imaging.BitmapAlphaMode]::Ignore, $transform,
                    [Windows.Graphics.Imaging.ExifOrientationMode]::RespectExifOrientation,
                    [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage
                )) ([Windows.Graphics.Imaging.SoftwareBitmap])
                try {
                    foreach ($engine in $engines) {
                        $result = Wait-Result ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
                        $lines = @(
                            foreach ($line in $result.Lines) {
                                $words = @(foreach ($word in $line.Words) {
                                    $r = $word.BoundingRect
                                    @{ text = $word.Text; x = $r.X / $scale; y = $r.Y / $scale;
                                       width = $r.Width / $scale; height = $r.Height / $scale }
                                })
                                @{ words = $words }
                            }
                        )
                        @{ lines = $lines }
                    }
                } finally { $bitmap.Dispose() }
            }
        )
        @{ passes = $passes } | ConvertTo-Json -Depth 8 -Compress
    } finally { $stream.Dispose() }
} catch {
    [Console]::Error.WriteLine($_)
    exit 1
}
"""


def calendar_ocr_command(path):
    program = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    environment = QProcessEnvironment.systemEnvironment()
    environment.insert('DDM_CALENDAR_IMAGE', str(Path(path).resolve()))
    command = b64encode(_SCRIPT.encode('utf-16-le')).decode('ascii')
    return str(program), ['-NoProfile', '-NonInteractive', '-EncodedCommand', command], environment
