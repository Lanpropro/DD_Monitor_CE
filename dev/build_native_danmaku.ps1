param(
    [string]$Python = "",
    [string]$BuildDir = "",
    [string]$InstallPrefix = "",
    [string]$SourceRoot = "",
    [string]$Generator = "",
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"

function Get-NativeConfigureArgs {
    param(
        [string]$SourceRoot,
        [string]$BuildDir,
        [string]$Python,
        [string]$PybindDir,
        [string]$Generator
    )

    $arguments = @(
        "-S", (Join-Path $SourceRoot "native"),
        "-B", $BuildDir,
        "-DPython_EXECUTABLE=$Python",
        "-Dpybind11_DIR=$PybindDir",
        "-DBUILD_TESTING=ON"
    )
    if ($Generator) {
        $arguments += @("-G", $Generator, "-A", "x64")
    }
    return $arguments
}

$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
if (-not $Python) { $Python = Join-Path $repo ".venv\Scripts\python.exe" }
if (-not $BuildDir) { $BuildDir = Join-Path $repo "work\native-build" }
if (-not $InstallPrefix) { $InstallPrefix = $repo }
if (-not $SourceRoot) { $SourceRoot = $repo }
$Python = (Resolve-Path -LiteralPath $Python).Path
$BuildDir = [IO.Path]::GetFullPath($BuildDir)
$InstallPrefix = [IO.Path]::GetFullPath($InstallPrefix)
$SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$cmake = (& $Python -c "import pathlib,cmake; print(pathlib.Path(cmake.CMAKE_BIN_DIR)/'cmake.exe')").Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $cmake)) { throw "Install requirements-dev.txt into the selected Python environment first" }
$ctest = Join-Path (Split-Path -Parent $cmake) "ctest.exe"
$pybind = (& $Python -m pybind11 --cmakedir).Trim()
if ($LASTEXITCODE -ne 0) { throw "pybind11 is unavailable in $Python" }
$configureArgs = Get-NativeConfigureArgs -SourceRoot $SourceRoot -BuildDir $BuildDir -Python $Python -PybindDir $pybind -Generator $Generator
& $cmake @configureArgs
if ($LASTEXITCODE -ne 0) { throw "Native CMake configuration failed" }
& $cmake --build $BuildDir --config Release
if ($LASTEXITCODE -ne 0) { throw "Native Release build failed" }
$testResult = "skipped"
if (-not $SkipTests) {
    & $ctest --test-dir $BuildDir -C Release --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw "Native CTest failed" }
    $testResult = "passed"
}
& $cmake --install $BuildDir --config Release --prefix $InstallPrefix
if ($LASTEXITCODE -ne 0) { throw "Native installation failed" }
$reportGenerator = if ($Generator) { $Generator } else { "default" }
$metadata = Join-Path $BuildDir "native-build.json"
@'
import hashlib, importlib, json, pathlib, platform, struct, subprocess, sys, sysconfig
repo, prefix, output = map(pathlib.Path, sys.argv[1:4])
source_root = pathlib.Path(sys.argv[6])
sys.path.insert(0, str(prefix))
module = importlib.import_module('ddm._native_danmaku')
module_path = pathlib.Path(module.__file__).resolve()
if not module_path.is_relative_to(prefix.resolve()):
    raise RuntimeError(f'Imported a module outside install prefix: {module_path}')
if module.contract_version != 1:
    raise RuntimeError('Unexpected native contract version')
if struct.calcsize('P') != 8 or not module_path.name.endswith(sysconfig.get_config_var('EXT_SUFFIX')):
    raise RuntimeError('Native extension architecture or Python ABI mismatch')
def git(*args):
    return subprocess.check_output(['git', '-C', str(repo), *args])
paths = {p.decode('utf-8') for p in git('ls-files', '-z').split(b'\0') if p}
paths.update(str(p.relative_to(source_root)).replace('\\', '/') for p in (source_root/'native').rglob('*') if p.is_file() and p.suffix in {'.cpp','.h','.txt','.md'})
manifest = {}
for rel in sorted(paths):
    path = source_root / rel
    if path.is_file() and path.suffix not in {'.pyd','.dll'}:
        manifest[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
tree = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
import PySide6, pybind11
report = {
    'configuration': 'Release', 'generator': sys.argv[5], 'ctest': sys.argv[4],
    'source_root': str(source_root),
    'base_commit': 'a5554729cf4a3a2ca9ee1fb713bd8703bb79168c',
    'source_commit': git('rev-parse','HEAD').decode().strip(),
    'source_dirty': bool(git('status','--porcelain').strip()),
    'tracked_patch_sha256': hashlib.sha256(git('diff','HEAD','--binary')).hexdigest(),
    'source_tree_sha256': hashlib.sha256(tree).hexdigest(), 'source_manifest': manifest,
    'python_executable': sys.executable, 'python_version': platform.python_version(),
    'python_tag': f'cp{sys.version_info.major}{sys.version_info.minor}',
    'extension_suffix': sysconfig.get_config_var('EXT_SUFFIX'), 'architecture': platform.machine(),
    'qt_version': PySide6.__version__, 'pybind11_version': pybind11.__version__,
    'module_path': str(module_path), 'module_sha256': hashlib.sha256(module_path.read_bytes()).hexdigest(),
    'contract_version': module.contract_version, 'import': 'passed'
}
output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'Native Release import passed: {module_path}; report={output}')
'@ | & $Python - $repo $InstallPrefix $metadata $testResult $reportGenerator $SourceRoot
if ($LASTEXITCODE -ne 0) { throw "Native import/ABI verification failed" }
Write-Output "Native build report: $metadata"
