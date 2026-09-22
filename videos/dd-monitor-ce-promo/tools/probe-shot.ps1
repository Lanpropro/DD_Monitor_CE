# probe-shot.ps1 -- inspect composition screenshots (raw/_var-*.png).
#
# Why: the model cannot view images, so composition framing must be verified
# numerically. This reads a PNG and reports, for each requested column:
#   darkRows  -- how many rows inside the expected window box are dark
#   cropEdge  -- first y where a bright run starts right after a dark run
#                (i.e. where the window's painting gets cut off)
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI,
# so UTF-8 comments turn into mojibake and can corrupt string literals.
#
# Usage:
#   & .\tools\probe-shot.ps1 -Files raw\_var-baseline.png -X 960
#   & .\tools\probe-shot.ps1 -Files (Get-ChildItem raw\_var-*.png).FullName -X 960
param(
  [Parameter(Mandatory = $true)][string[]]$Files,
  [int[]]$X = @(960),
  [int]$WinTop = 236,
  [int]$WinBot = 783,
  [double]$DarkLum = 60,
  [double]$BrightLum = 100,
  [int]$RunLen = 15
)
Add-Type -AssemblyName System.Drawing

foreach ($f in $Files) {
  if (-not (Test-Path $f)) { Write-Output ("MISSING  " + $f); continue }
  $bmp = [System.Drawing.Bitmap]::FromFile((Resolve-Path $f))
  $parts = @()
  foreach ($col in $X) {
    # luminance per row
    $lum = New-Object 'double[]' $bmp.Height
    for ($y = 0; $y -lt $bmp.Height; $y++) {
      $c = $bmp.GetPixel($col, $y)
      $lum[$y] = 0.299 * $c.R + 0.587 * $c.G + 0.114 * $c.B
    }
    $dark = 0
    for ($y = $WinTop; $y -le [Math]::Min($WinBot, $bmp.Height - 1); $y++) { if ($lum[$y] -lt $DarkLum) { $dark++ } }
    $edge = -1
    for ($y = $WinTop + $RunLen; $y -lt $bmp.Height - $RunLen; $y++) {
      if ($lum[$y] -lt $BrightLum) { continue }
      $ok = $true
      for ($k = 1; $k -le $RunLen; $k++) { if ($lum[$y - $k] -ge $DarkLum) { $ok = $false; break } }
      if ($ok) { $edge = $y; break }
    }
    $parts += ("x={0} dark={1}/{2} cropEdge={3}" -f $col, $dark, ($WinBot - $WinTop + 1), $edge)
  }
  Write-Output ("{0,-26} {1}" -f (Split-Path $f -Leaf), ($parts -join "   "))
  $bmp.Dispose()
}
