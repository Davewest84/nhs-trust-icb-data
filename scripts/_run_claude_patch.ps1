# Bootstrap for the weekly Claude-orchestrated NHS trust + ICB data refresh.
# Task Scheduler invokes this file at Saturday 05:00.
#
# Finds the latest installed claude.exe at run time (so the task survives
# VSCode extension updates), then invokes it with a prompt that tells Claude
# to read scripts/url_update_schedule_prompt.md and follow it.
#
# Captures all of Claude's stdout/stderr to a timestamped log file outside
# the repo, and verifies a git commit was actually made (HEAD before vs after).
# Writes a status sentinel file so failures aren't silent — Task Scheduler's
# "LastTaskResult: 0" alone is not enough.

$ErrorActionPreference = 'Stop'

# Repo working directory. This is the public nhs-trust-icb-data clone — the
# canonical home for all four NHS data files since the May 2026 consolidation.
$repo = "C:\Users\davew\nhs-trust-icb-data"

# Log + status sentinel outside the repo so they're not committed.
$logDir = Join-Path $env:USERPROFILE "AppData\Local\Temp\nhs-trust-icb-data-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$logFile = Join-Path $logDir "refresh-$timestamp.log"
$statusFile = Join-Path $logDir "last-status.txt"

function Write-Log($msg) {
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg" | Out-File -FilePath $logFile -Append -Encoding utf8
}

Set-Location $repo
Write-Log "Refresh run started. Repo: $repo"

# Sync the repo to origin/main before running. If anything's accumulated
# locally (a previous run that didn't push, or manual edits), we don't want
# to start from stale state.
& git fetch origin main 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
$divergence = & git rev-list --left-right --count HEAD...origin/main 2>$null
Write-Log "HEAD vs origin/main: $divergence  (LHS=local-ahead, RHS=remote-ahead)"
if ($divergence -match '^\d+\s+[1-9]') {
    # Remote ahead — fast-forward if we can
    & git pull --ff-only origin main 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
    Write-Log "Pulled remote changes."
}

# Find latest claude.exe
$extRoot = "$env:USERPROFILE\.vscode\extensions"
$claudeExe = @(Get-ChildItem -Path $extRoot -Filter "anthropic.claude-code-*-win32-x64" -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName "resources\native-binary\claude.exe" } |
    Where-Object { Test-Path $_ })[0]

if (-not $claudeExe) {
    Write-Log "ERROR: claude.exe not found under $extRoot"
    "$(Get-Date -Format 'o') FAIL no-claude-exe" | Out-File -FilePath $statusFile -Encoding utf8
    exit 1
}
Write-Log "Using claude.exe: $claudeExe"

# Record HEAD before — so we can detect whether Claude made a commit.
$headBefore = & git rev-parse HEAD 2>$null
Write-Log "HEAD before: $headBefore"

$prompt = "Read scripts/url_update_schedule_prompt.md and execute the instructions in that file's 'Prompt to paste' block. Stay strictly within the 'Safety rules' section. The working directory is the current directory."

Write-Log "Invoking Claude via Start-Process (prompt piped via stdin)"
"---- BEGIN CLAUDE OUTPUT ----" | Out-File -FilePath $logFile -Append -Encoding utf8
$promptTmp = "$logFile.prompt.tmp"
$stdoutTmp = "$logFile.stdout.tmp"
$stderrTmp = "$logFile.stderr.tmp"
[System.IO.File]::WriteAllText($promptTmp, $prompt, (New-Object System.Text.UTF8Encoding $false))
$proc = Start-Process -FilePath $claudeExe `
    -ArgumentList @('-p', '--permission-mode', 'bypassPermissions') `
    -WorkingDirectory $repo `
    -RedirectStandardInput $promptTmp `
    -RedirectStandardOutput $stdoutTmp `
    -RedirectStandardError $stderrTmp `
    -Wait -NoNewWindow -PassThru
$claudeExit = $proc.ExitCode
Remove-Item $promptTmp -Force -ErrorAction SilentlyContinue

# Capture Claude's output to the main log. Wrapped in try/catch so a transient
# failure here (encoding glitch, file lock) doesn't kill the rest of the script
# — the data update is the important bit and has already happened.
try {
    if (Test-Path $stdoutTmp) {
        Get-Content -Path $stdoutTmp -Raw | Out-File -FilePath $logFile -Append -Encoding utf8
        Remove-Item $stdoutTmp -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $stderrTmp) {
        if ((Get-Item $stderrTmp).Length -gt 0) {
            "---- STDERR ----" | Out-File -FilePath $logFile -Append -Encoding utf8
            Get-Content -Path $stderrTmp -Raw | Out-File -FilePath $logFile -Append -Encoding utf8
        }
        Remove-Item $stderrTmp -Force -ErrorAction SilentlyContinue
    }
    "---- END CLAUDE OUTPUT ----" | Out-File -FilePath $logFile -Append -Encoding utf8
} catch {
    Write-Log "WARNING: Post-Claude output capture failed: $($_.Exception.Message). Continuing with HEAD check."
}
Write-Log "Claude exited with code: $claudeExit"

# Did Claude actually commit anything?
$headAfter = & git rev-parse HEAD 2>$null
Write-Log "HEAD after: $headAfter"

if ($headBefore -eq $headAfter) {
    Write-Log "WARNING: HEAD unchanged. Claude ran but made no commit. (No URL changes + no contacts in this batch?)"
    "$(Get-Date -Format 'o') FAIL no-commit (claude exit=$claudeExit, log=$logFile)" | Out-File -FilePath $statusFile -Encoding utf8
    exit 2
} else {
    Write-Log "OK: New commit created. HEAD moved $headBefore -> $headAfter"
    "$(Get-Date -Format 'o') OK $headAfter (log=$logFile)" | Out-File -FilePath $statusFile -Encoding utf8
}

# Prune old logs (keep last 12 weeks)
Get-ChildItem -Path $logDir -Filter "refresh-*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 12 |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit 0
