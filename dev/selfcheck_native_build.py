"""Check PowerShell syntax and exercise release cleanup path boundaries."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


def check_launchers(repo: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="ddm-launcher-check-") as temporary:
        root = Path(temporary)
        scripts = root / ".venv/Scripts"
        scripts.mkdir(parents=True)
        source = root / "Probe.cs"
        source.write_text('using System; using System.IO; class Probe { static void Main() {'
                          'File.WriteAllText(Environment.GetEnvironmentVariable("DDM_LAUNCH_PROBE"),'
                          'Environment.GetEnvironmentVariable("DDM_QTQUICK_DANMAKU") ?? "unset"); }}',
                          encoding="utf-8")
        compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework/v4.0.30319/csc.exe"
        subprocess.run([str(compiler), "/nologo", "/target:winexe",
                        "/out:" + str(scripts / "python.exe"), str(source)], check=True)
        shutil.copyfile(scripts / "python.exe", scripts / "pythonw.exe")
        for name in ("run.cmd", "run-console.cmd"):
            shutil.copyfile(repo / name, root / name)
            for override in (None, "0", "1"):
                output = root / (name + str(override) + ".txt")
                env = dict(os.environ, DDM_LAUNCH_PROBE=str(output))
                env.pop("DDM_QTQUICK_DANMAKU", None)
                if override is not None:
                    env["DDM_QTQUICK_DANMAKU"] = override
                subprocess.run(["cmd.exe", "/d", "/c", str(root / name)], cwd=root,
                               env=env, input="\n", text=True, capture_output=True,
                               check=True, timeout=15)
                deadline = time.monotonic() + 5
                while not output.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                assert output.read_text() == (override or "0"), (name, override)


def main() -> None:
    if sys.platform != "win32":
        print("SKIP: Windows PowerShell build checks require Windows")
        return
    repo = Path(__file__).resolve().parents[1]
    check_launchers(repo)
    cmake_version = next(
        line.split("==", 1)[1]
        for line in (repo / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
        if line.startswith("cmake==")
    )
    if tuple(map(int, re.match(r"(\d+)\.(\d+)", cmake_version).groups())) < (4, 2):
        raise RuntimeError("CMake 4.2 or newer is required for the Visual Studio 2026 generator")
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
    } else {
        if ($ast.Extent.Text -match 'Visual Studio 17 2022') {
            throw 'Native build must not pin a Visual Studio version'
        }
        $generatorParameter = $ast.ParamBlock.Parameters | Where-Object {
            $_.Name.VariablePath.UserPath -eq 'Generator'
        }
        if ($generatorParameter.DefaultValue.Extent.Text -notin @("''", '""')) {
            throw 'Native build generator must default to automatic selection'
        }
        $functions = $ast.FindAll({
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq 'Get-NativeConfigureArgs'
        }, $true)
        if ($functions.Count -ne 1) { throw 'Native configure argument builder is missing' }
        Invoke-Expression $functions[0].Extent.Text
        $common = @('-SourceRoot', 'C:\repo', '-BuildDir', 'C:\build', '-Python', 'python.exe',
                    '-PybindDir', 'C:\pybind')
        $automatic = @(Get-NativeConfigureArgs @common -Generator '')
        if ($automatic -contains '-G' -or $automatic -contains '-A') {
            throw 'Automatic generator selection must not pass -G or -A'
        }
        $explicit = @(Get-NativeConfigureArgs @common -Generator 'Visual Studio 17 2022')
        $generatorIndex = [Array]::IndexOf($explicit, '-G')
        $architectureIndex = [Array]::IndexOf($explicit, '-A')
        if ($generatorIndex -lt 0 -or $explicit[$generatorIndex + 1] -ne 'Visual Studio 17 2022' -or
            $architectureIndex -lt 0 -or $explicit[$architectureIndex + 1] -ne 'x64') {
            throw 'Explicit native generation must pass its generator and x64 architecture'
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
Write-Output 'PASS: PowerShell syntax, native generator selection, UTF-8 JSON paths/hashes, cleanup boundaries, traversal rejection and junction preservation'
""", encoding="utf-8")
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(script), "-Repo", str(repo), "-Scratch", temporary,
                        "-ExpectedModulePath", str(module)],
                       check=True, timeout=30)


if __name__ == "__main__":
    main()
