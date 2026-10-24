"""Check PowerShell syntax and exercise release cleanup path boundaries."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> None:
    if sys.platform != "win32":
        print("SKIP: Windows PowerShell build checks require Windows")
        return
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="ddm-build-path-check-") as temporary:
        scratch = Path(temporary)
        module = scratch / "DD监控室CE" / "_internal" / "ddm" / "_native_danmaku.cp313-win_amd64.pyd"
        module.parent.mkdir(parents=True)
        module.write_bytes(b"unicode-path-regression")
        fixture = {"module_path": str(module), "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest()}
        for relative in ("ddm/assets/licenses/libmpv-SOURCE.json", "native-build/native-build.json", "probe.json"):
            path = scratch / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        script = scratch / "check.ps1"
        script.write_text(r"""
param([string]$Repo, [string]$Scratch, [string]$ExpectedModulePath)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility')
$tokens = $null; $errors = $null
$sourceRepo = $Repo
foreach ($name in @('build_release.ps1', 'build_native_danmaku.ps1')) {
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $sourceRepo "dev\$name"), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    if ($name -eq 'build_release.ps1') {
        $functions = $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]}, $true)
        foreach ($function in $functions) { Invoke-Expression $function.Extent.Text }
        $jsonReads = $ast.FindAll({param($node)
            $node -is [Management.Automation.Language.PipelineAst] -and
            $node.Extent.Text -match '^Get-Content\b.*\|\s*ConvertFrom-Json$'
        }, $true)
        if ($jsonReads.Count -ne 3) { throw 'Release JSON input coverage changed; update encoding regression fixtures' }
        $repo = $Scratch
        $freezeBuild = Join-Path $Scratch 'native-build'
        $probeOutput = Join-Path $Scratch 'probe.json'
        foreach ($read in $jsonReads) {
            $decoded = Invoke-Expression $read.Extent.Text
            if ($decoded.module_path -cne $ExpectedModulePath) { throw 'UTF-8 JSON path did not round trip under Windows PowerShell' }
            Assert-BuildChild $decoded.module_path (Split-Path (Split-Path $ExpectedModulePath -Parent) -Parent)
            if ((Get-FileHash -LiteralPath $decoded.module_path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $decoded.module_sha256) {
                throw 'UTF-8 JSON decoded path did not locate the original native module'
            }
        }
    }
}
$root = Join-Path $Scratch 'root'
$sibling = Join-Path $Scratch 'root-other'
New-Item -ItemType Directory -Path $root, $sibling | Out-Null
Assert-BuildChild (Join-Path $root 'child\missing') $root
foreach ($bad in @($root, $sibling, (Join-Path $root '..\root-other\sentinel'))) {
    $rejected = $false
    try { Assert-BuildChild $bad $root } catch { $rejected = $true }
    if (-not $rejected) { throw "Unsafe cleanup path accepted: $bad" }
}
$sentinel = Join-Path $sibling 'sentinel'
Set-Content -LiteralPath $sentinel -Value 'keep'
$child = Join-Path $root 'child'
New-Item -ItemType Directory -Path $child | Out-Null
Set-Content -LiteralPath (Join-Path $child 'temporary') -Value 'remove'
Remove-BuildPath $child $root
if (Test-Path -LiteralPath $child) { throw 'Owned build child was not removed' }
$link = Join-Path $root 'linked'
New-Item -ItemType Junction -Path $link -Target $sibling | Out-Null
$rejected = $false
try { Remove-BuildPath $link $root } catch { $rejected = $true }
if (-not $rejected -or -not (Test-Path -LiteralPath $sentinel)) { throw 'Junction escaped cleanup boundary' }
Write-Output 'PASS: PowerShell syntax, UTF-8 JSON paths/hashes, cleanup boundaries, traversal rejection and junction preservation'
""", encoding="utf-8")
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(script), "-Repo", str(repo), "-Scratch", temporary,
                        "-ExpectedModulePath", str(module)],
                       check=True, timeout=30)


if __name__ == "__main__":
    main()
