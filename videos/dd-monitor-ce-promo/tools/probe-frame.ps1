# 单帧像素探针：给一段渲染好的 mp4，在指定时间抓一帧，沿某一列/某几列做亮度剖面。
# 用途：模型无法"看"图，用数值确认构图（软件窗口在画布上的实际可见高度、颜色、位置）。
#
# 例：
#   pwsh -File tools/probe-frame.ps1 -Video renders/_probe-01.mp4 -Time 3.9 -X 960
#   pwsh -File tools/probe-frame.ps1 -Video renders/_probe-01.mp4 -Time 3.9 -X 960 -Rows
param(
  [Parameter(Mandatory = $true)][string]$Video,
  [double]$Time = 3.9,
  [int[]]$X = @(960),
  [double]$DarkLum = 90,
  [switch]$Rows,
  [int]$Step = 40
)

Add-Type -AssemblyName System.Drawing

if (-not (Test-Path "raw")) { New-Item -ItemType Directory -Path "raw" | Out-Null }
$png = Join-Path (Get-Location) ("raw\_probe-" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".png")

& ffmpeg -y -loglevel error -ss $Time -i $Video -frames:v 1 $png
if (-not (Test-Path $png)) { Write-Output "FRAME GRAB FAILED at $Time"; exit 1 }

$bmp = [System.Drawing.Bitmap]::FromFile($png)
Write-Output ("frame {0}x{1} @ {2}s" -f $bmp.Width, $bmp.Height, $Time)

foreach ($col in $X) {
  $darkCount = 0; $first = -1; $last = -1
  for ($y = 0; $y -lt $bmp.Height; $y++) {
    $c = $bmp.GetPixel($col, $y)
    $lum = 0.299 * $c.R + 0.587 * $c.G + 0.114 * $c.B
    if ($lum -lt $DarkLum) {
      $darkCount++
      if ($first -lt 0) { $first = $y }
      $last = $y
    }
  }
  Write-Output ("x={0,5}  dark rows {1,4} / {2}   span y {3}..{4}" -f $col, $darkCount, $bmp.Height, $first, $last)
}

if ($Rows) {
  Write-Output "--- vertical luminance profile (step $Step) ---"
  $col = $X[0]
  for ($y = 0; $y -lt $bmp.Height; $y += $Step) {
    $c = $bmp.GetPixel($col, $y)
    $lum = [int](0.299 * $c.R + 0.587 * $c.G + 0.114 * $c.B)
    $bar = "#" * [int]($lum / 4)
    Write-Output ("y={0,4} lum={1,3} #{2:X2}{3:X2}{4:X2} {5}" -f $y, $lum, $c.R, $c.G, $c.B, $bar)
  }
}

$bmp.Dispose()
Remove-Item $png -ErrorAction SilentlyContinue
