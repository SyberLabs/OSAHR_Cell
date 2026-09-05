param([switch]$Benchmark)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create the repository .venv and install ontology-kernel/requirements.txt and pytest first. See README.md.'
}
$previousPythonPath = $env:PYTHONPATH
Push-Location -LiteralPath $repoPath
try {
    $env:PYTHONPATH = "$repoPath;$repoPath\grokcell;$PSScriptRoot"
    $scratchPath = Join-Path $PSScriptRoot ('scratch\check-' + [guid]::NewGuid().ToString('N'))
    & $pythonPath -m pytest ontology-kernel/test_profile.py -p no:cacheprovider "--basetemp=$scratchPath"
    if ($LASTEXITCODE -ne 0) { throw 'Profile checks failed.' }
    & $pythonPath ontology-kernel/demo.py
    if ($LASTEXITCODE -ne 0) { throw 'Demo failed.' }
    if ($Benchmark) {
        & $pythonPath ontology-kernel/benchmark.py
        if ($LASTEXITCODE -ne 0) { throw 'Benchmark failed.' }
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
