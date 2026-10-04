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
# python -m video_rpa.cli multi --folder "F:\Download\4.6-月升之前-與獸共舞" --desc "劇情" --tags "崩壞星穹鐵道,honkaistarrail,月升之前-與獸共舞" --playlist "崩壞:星穹鐵道"
# python -m video_rpa.cli multi --folder "F:\Download\2026-09-14-虛構敘事-立界開篇" --desc "練度展示於結尾" --tags "崩壞星穹鐵道,honkaistarrail,立界開篇" --playlist "崩壞:星穹鐵道-高難"
python -m video_rpa.cli multi --folder "F:\Download\2026-09-29-忘卻之庭-來生泅渡" --desc "練度展示於結尾" --tags "崩壞星穹鐵道,honkaistarrail,來生泅渡" --playlist "崩壞:星穹鐵道-高難"
# python -m video_rpa.cli multi --folder "F:\Download\2026-09-28-異相仲裁-落葉歸根-絕境王棋" --desc "練度展示於結尾" --tags "崩壞星穹鐵道,honkaistarrail,落葉歸根" --playlist "崩壞:星穹鐵道-高難"
# python -m video_rpa.cli multi --folder "F:\Download\2026-09-30-末日幻影-仙客天狼" --desc "練度展示於結尾,還是太簡單了" --tags "崩壞星穹鐵道,honkaistarrail,仙客天狼" --playlist "崩壞:星穹鐵道-高難"
# python -m video_rpa.cli multi --folder "F:\Download\2026-08-30-末日幻影-仙客天狼" --desc "練度展示於結尾,還是太簡單了" --tags "崩壞星穹鐵道,honkaistarrail,仙客天狼" --playlist "崩壞:星穹鐵道-高難"