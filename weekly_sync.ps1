# weekly_sync.ps1 - Channel Brain weekly delta sync (all active clients)
# Task Scheduler runs the copy at C:\Users\skybo\weekly_sync.ps1 (outside OneDrive).
# This repo copy is the master - re-copy after editing.
Start-Transcript -Path "$env:USERPROFILE\weekly_sync_last_transcript.txt" -Force
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Users\skybo\OneDrive\Documents\Businesses\YouTube Scraper\files"
New-Item -ItemType Directory -Force -Path sync_logs | Out-Null
$log = "sync_logs\sync_$(Get-Date -Format 'yyyy-MM-dd_HHmm').log"
python sync_runner.py 2>&1 | Out-File -FilePath $log -Encoding utf8
if ($LASTEXITCODE -eq 0) {
    Add-Content $log "SYNC OK $(Get-Date)"
} else {
    Add-Content $log "SYNC FAILED $(Get-Date) exit=$LASTEXITCODE"
}
Stop-Transcript
