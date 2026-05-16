# Installs two Windows scheduled tasks:
#   1. Weekly URL health check (runs check_urls.py -- covers BOTH trust_urls.json
#      AND icb_urls.json, Sundays 04:00)
#   2. Weekly Claude-orchestrated patch (reads both reports, fixes broken URLs,
#      Sundays 05:00)
#
# Run ONCE (normal user PowerShell is fine -- tasks register under current user):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install-scheduled-check.ps1
#
# Uninstall with:
#   Unregister-ScheduledTask -TaskName "HSJ - URL health check (weekly)" -Confirm:$false
#   Unregister-ScheduledTask -TaskName "HSJ - URL patch (weekly)" -Confirm:$false
#
# Legacy task names from before the trust+ICB merge (unregister these too if upgrading):
#   Unregister-ScheduledTask -TaskName "HSJ - Trust URL health check (weekly)" -Confirm:$false
#   Unregister-ScheduledTask -TaskName "HSJ - Trust URL patch (weekly)" -Confirm:$false

$ErrorActionPreference = 'Stop'

$repo = "C:\Users\davew\OneDrive - HSJ Information Ltd\Claude code assistant\HSJ projects\Team AI tools\railway-prototype"
$promptFile = Join-Path $repo "scripts\url_update_schedule_prompt.md"
$wrapper = Join-Path $repo "scripts\_run_claude_patch.ps1"

if (-not (Test-Path $repo)) {
    Write-Error "Repo path not found: $repo"
    exit 1
}
if (-not (Test-Path $promptFile)) {
    Write-Error "Schedule prompt file not found: $promptFile"
    exit 1
}

# --- Locate py.exe ---
$pyExe = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
if (-not $pyExe) {
    Write-Error "py.exe not on PATH. Install the Python launcher first."
    exit 1
}
Write-Host "Found py.exe: $pyExe"

# --- Verify claude.exe is reachable (via VSCode extension) ---
$extRoot = "$env:USERPROFILE\.vscode\extensions"
$claudeTest = @(Get-ChildItem -Path $extRoot -Filter "anthropic.claude-code-*-win32-x64" -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName "resources\native-binary\claude.exe" } |
    Where-Object { Test-Path $_ })
if ($claudeTest.Count -eq 0) {
    Write-Warning "claude.exe not found under $extRoot. Task 1 installs but Task 2 will be skipped."
} else {
    Write-Host "Found claude.exe (latest): $($claudeTest[0])"
}

# --- Verify Task 2 wrapper exists (canonical version is committed in git) ---
# We do NOT rewrite the wrapper here. The canonical version is committed in
# git at scripts/_run_claude_patch.ps1 with full logging. Earlier versions of
# this install script wrote an inline (no-logging) heredoc which clobbered the
# logged wrapper on every install. That footgun is removed.
if (-not (Test-Path $wrapper)) {
    Write-Error "Wrapper not found at $wrapper. It should be committed in git. Run: git restore scripts/_run_claude_patch.ps1"
    exit 1
}
Write-Host "Found wrapper: $wrapper"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

# ==== Task 1: health check (covers BOTH trust_urls.json and icb_urls.json) ====
$action1 = New-ScheduledTaskAction `
    -Execute $pyExe `
    -Argument "scripts/check_urls.py" `
    -WorkingDirectory $repo
$trigger1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "04:00"
Register-ScheduledTask `
    -TaskName "HSJ - URL health check (weekly)" `
    -Action $action1 `
    -Trigger $trigger1 `
    -Settings $settings `
    -Description "Runs scripts/check_urls.py -- walks data/trust_urls.json and data/icb_urls.json, writes trust_urls_report.json + icb_urls_report.json. Takes ~9-10 minutes." `
    -Force | Out-Null
Write-Host "Installed: HSJ - URL health check (weekly)"

# ==== Task 2: Claude-orchestrated patch ====
if ($claudeTest.Count -gt 0) {
    $action2 = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`"" `
        -WorkingDirectory $repo
    $trigger2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "05:00"
    $settings2 = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask `
        -TaskName "HSJ - URL patch (weekly)" `
        -Action $action2 `
        -Trigger $trigger2 `
        -Settings $settings2 `
        -Description "Claude reads trust_urls_report.json + icb_urls_report.json, patches broken URLs in both DBs, commits, pushes. Wrapper finds latest claude.exe at run time." `
        -Force | Out-Null
    Write-Host "Installed: HSJ - URL patch (weekly)"
} else {
    Write-Host "Skipped Task 2 (no claude.exe found)."
}

Write-Host ""
Write-Host "Verify with:  Get-ScheduledTask -TaskName 'HSJ - *'"
Write-Host "Run once:     Start-ScheduledTask -TaskName 'HSJ - Trust URL health check (weekly)'"
