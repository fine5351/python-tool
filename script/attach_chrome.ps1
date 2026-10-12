# 自動定位專案 src 目錄並加入 PYTHONPATH
$baseDirs = @()
if ($PSScriptRoot) { $baseDirs += $PSScriptRoot }
if ($MyInvocation.MyCommand.Definition) {
    $defDir = Split-Path -Parent $MyInvocation.MyCommand.Definition -ErrorAction SilentlyContinue
    if ($defDir) { $baseDirs += $defDir }
}
$baseDirs += $PWD.Path

$srcDir = $null
foreach ($dir in $baseDirs) {
    $candidates = @((Join-Path $dir "..\src"), (Join-Path $dir "src"))
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $srcDir = (Resolve-Path $c).Path
            break
        }
    }
    if ($srcDir) { break }
}

if ($srcDir) {
    $env:PYTHONPATH = if ($env:PYTHONPATH) { "$srcDir;$env:PYTHONPATH" } else { $srcDir }
}
$env:PYTHONUNBUFFERED = "1"

$pythonCmd = "python"
if (-not (Get-Command $pythonCmd -ErrorAction SilentlyContinue)) {
    if (Get-Command "py" -ErrorAction SilentlyContinue) {
        $pythonCmd = "py"
    }
    else {
        $candidates = @(
            "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
            "$env:LOCALAPPDATA\Microsoft\WindowsApps\python.exe",
            "C:\Program Files\Python313\python.exe"
        )
        foreach ($c in $candidates) {
            if (Test-Path $c) {
                $pythonCmd = $c
                break
            }
        }
    }
}

$scriptPath = Join-Path $PSScriptRoot "attach_chrome.py"
& $pythonCmd $scriptPath @args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
