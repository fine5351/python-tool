param (
    [int]$Port = 9222,
    [string]$DataDir = "d:/work/workspace/java/rpa/chrome-data"
)

$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chromePath)) {
    $chromeCmd = Get-Command "chrome.exe" -ErrorAction SilentlyContinue
    if ($chromeCmd) {
        $chromePath = $chromeCmd.Source
    } else {
        Write-Error "找不到 Google Chrome 執行檔 (chrome.exe)。"
        exit 1
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "🚀 正在以遠端除錯模式啟動 Google Chrome..." -ForegroundColor Green
Write-Host "  • 除錯埠號 (Port) : $Port" -ForegroundColor Yellow
Write-Host "  • 使用者資料目錄   : $DataDir" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

Start-Process -FilePath $chromePath -ArgumentList @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$DataDir",
    "--remote-allow-origins=*",
    "--no-first-run",
    "--no-default-browser-check"
)

Write-Host "✅ Chrome 已啟動！您可以隨時執行 .\script\attach_chrome.ps1 接入控制。" -ForegroundColor Green
