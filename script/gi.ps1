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
    } else {
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

# & $pythonCmd -m video_rpa.cli multi --folder "F:\Download\逐月節" --desc "劇情" --tags "原神,gensinimpact,逐月節" --playlist "原神"
# & $pythonCmd -m video_rpa.cli multi --folder "F:\傳說任務-狡兔之章" --desc "劇情" --tags "原神,gensinimpact,洛恩,狡兔之章" --playlist "原神"
& $pythonCmd -m video_rpa.cli multi --folder "F:\Download\2026-10-04-幻想真境劇詩" --desc "簡簡單單" --tags "原神,gensinimpact" --playlist "原神-高難" @args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}