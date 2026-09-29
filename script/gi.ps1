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
python -m video_rpa.cli multi --folder "F:\Download\逐月節" --desc "劇情" --tags "原神,gensinimpact,逐月節" --playlist "原神"
# python -m video_rpa.cli multi --folder "F:\傳說任務-狡兔之章" --desc "劇情" --tags "原神,gensinimpact,洛恩,狡兔之章" --playlist "原神"
# python -m video_rpa.cli multi --folder "F:\Download\2026-09-05-幻想真境劇詩" --desc "練度展示於結尾" --tags "原神,gensinimpact" --playlist "原神-高難"
# python -m video_rpa.cli multi --folder "F:\Download\2026-09-15-淵月螺旋" --desc "練度展示於結尾" --tags "原神,gensinimpact" --playlist "原神-高難"