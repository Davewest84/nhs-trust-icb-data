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

# Resolve a Python launcher for the summary email (py, then python).
$pyCmd = Get-Command py -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command python -ErrorAction SilentlyContinue }
$pyExe = if ($pyCmd) { $pyCmd.Source } else { $null }
$sendEmailScript = "C:\Users\davew\OneDrive - HSJ Information Ltd\Claude code assistant\tools\send_email.py"

# Emails Dave a weekly summary to Gmail. Best-effort: a failure here is logged but
# never aborts the run. Called on every exit path so it doubles as a heartbeat —
# Dave gets an email each Saturday whether or not anything changed. Pulls the
# commit list for the run and inlines the ODS reconciliation flags (step 8).
function Send-Summary($status) {
    try {
        if (-not $pyExe) { Write-Log "WARNING: no python launcher found - summary email skipped."; return }
        $date = Get-Date -Format "yyyy-MM-dd"
        $lines = @("Weekly NHS trust + ICB data refresh - $date", "Status: $status", "")

        if ($headBefore -and $headAfter -and ($headBefore -ne $headAfter)) {
            $lines += "Commits this run:"
            $log = & git log "$headBefore..$headAfter" --pretty=format:"  %h  %s" 2>$null
            if ($log) { $lines += $log }
            $lines += ""
        } else {
            $lines += "No commit made this run."
            $lines += ""
        }

        $reconPath = Join-Path $repo "ods_reconciliation_report.json"
        if (Test-Path $reconPath) {
            try {
                $recon = Get-Content $reconPath -Raw | ConvertFrom-Json
                $adds = @($recon.add_candidates)
                $removes = @($recon.remove_candidates)
                $lines += "ODS reconciliation (action needed if non-zero):"
                $lines += "  To ADD (live in ODS, missing from DB): $($adds.Count)"
                foreach ($a in $adds) { $lines += "    + $($a.ods)  $($a.name)  [$($a.role)]  region~$($a.suggested_region)" }
                $lines += "  To REMOVE (gone from ODS, still in DB): $($removes.Count)"
                foreach ($r in $removes) { $lines += "    - $($r.ods)  $($r.name) -> successor $($r.successor_ods) $($r.successor_name) (legal end $($r.legal_end))" }
                if ($adds.Count -eq 0 -and $removes.Count -eq 0) { $lines += "  (no membership changes flagged this week)" }
            } catch {
                $lines += "ODS reconciliation report present but unparseable: $($_.Exception.Message)"
            }
        } else {
            $lines += "ODS reconciliation report not found (step 8 may not have completed)."
        }
        $lines += ""
        $lines += "Full log: $logFile"

        $body = ($lines -join "`n")
        $bodyTmp = "$logFile.email.txt"
        [System.IO.File]::WriteAllText($bodyTmp, $body, (New-Object System.Text.UTF8Encoding $false))
        $subject = "NHS data refresh $date - $status"
        & $pyExe $sendEmailScript send --account gmail --to "davewest84@gmail.com" --subject $subject --body-file $bodyTmp 2>&1 |
            Out-File -FilePath $logFile -Append -Encoding utf8
        Remove-Item $bodyTmp -Force -ErrorAction SilentlyContinue
        Write-Log "Summary email sent to Gmail (status=$status)."
    } catch {
        Write-Log "WARNING: summary email failed: $($_.Exception.Message)"
    }
}

Set-Location $repo
Write-Log "Refresh run started. Repo: $repo"

# Sync the repo to origin/main before running. If anything's accumulated
# locally (a previous run that didn't push, or manual edits), we don't want
# to start from stale state.
#
# Native git writes informational text ("From https://...") to stderr even on
# success, which under $ErrorActionPreference='Stop' triggers a NativeCommandError
# and kills the script. We localise EAP to 'Continue' around git invocations
# so they can complete normally.
$savedEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& git fetch origin main 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
$divergence = & git rev-list --left-right --count HEAD...origin/main 2>$null
Write-Log "HEAD vs origin/main: $divergence  (LHS=local-ahead, RHS=remote-ahead)"
if ($divergence -match '^\d+\s+[1-9]') {
    # Remote ahead — fast-forward if we can
    & git pull --ff-only origin main 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
    Write-Log "Pulled remote changes."
}
$ErrorActionPreference = $savedEAP

# Load GITHUB_TOKEN from the parent project's .env so Claude's `git push`
# can authenticate headlessly. Without this, plain `git push` hangs forever
# in git-credential-manager waiting for a UI prompt that nobody can see.
$envFile = "C:\Users\davew\OneDrive - HSJ Information Ltd\Claude code assistant\.claude\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | Where-Object { $_ -match '^\s*export\s+GITHUB_TOKEN\s*=' } | ForEach-Object {
        if ($_ -match '=\s*"?([^"]+)"?\s*$') {
            $env:GITHUB_TOKEN = $Matches[1].Trim('"')
            Write-Log "Loaded GITHUB_TOKEN from .env (length: $($env:GITHUB_TOKEN.Length))"
        }
    }
} else {
    Write-Log "WARNING: $envFile not found — GITHUB_TOKEN unavailable, headless push will hang"
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
    Send-Summary "FAIL no-claude-exe"
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
    # Claude made no commit. Before declaring failure, check whether it died
    # AFTER doing real work but BEFORE committing (session limit, premature
    # exit). If validated changes are sitting on disk, salvage them here so the
    # work isn't stranded — this is the failure mode that lost the 4 June run.
    Write-Log "HEAD unchanged after Claude session. Checking for stranded uncommitted data changes..."

    $savedEAP2 = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $trackedDirty = & git diff --name-only 2>$null   # modified/deleted TRACKED files only

    if ($trackedDirty) {
        Write-Log "Found uncommitted tracked changes:`n$($trackedDirty -join "`n")"

        # Guard against committing a half-written file: if a session died
        # mid-write, the data JSON could be corrupt. Both URL JSONs must parse
        # before we commit anything.
        $jsonOk = $true
        if ($pyExe) {
            & $pyExe -c "import json; json.load(open('trust_urls.json',encoding='utf-8')); json.load(open('icb_urls.json',encoding='utf-8'))" 2>&1 |
                Out-File -FilePath $logFile -Append -Encoding utf8
            if ($LASTEXITCODE -ne 0) { $jsonOk = $false }
        } else {
            Write-Log "WARNING: no python launcher — cannot validate JSON before salvage; proceeding cautiously."
        }

        if (-not $jsonOk) {
            $ErrorActionPreference = $savedEAP2
            Write-Log "ERROR: trust_urls.json / icb_urls.json failed to parse — NOT committing (possible mid-write corruption). Leaving working tree dirty for manual review."
            "$(Get-Date -Format 'o') FAIL no-commit-bad-json (claude exit=$claudeExit, log=$logFile)" | Out-File -FilePath $statusFile -Encoding utf8
            Send-Summary "FAIL no-commit-bad-json"
            exit 3
        }

        # Rebuild CSV/XLSX derivatives + index.html so they match the salvaged JSON.
        if ($pyExe) {
            & $pyExe (Join-Path $repo "scripts\build_derivatives.py") 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
        }

        # Stage only tracked changes (-u) so stray scratch/log files are never
        # committed; explicitly add the known derivatives in case any are untracked.
        & git add -u 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
        & git add -- trust_urls.csv trust_urls.xlsx icb_urls.csv icb_urls.xlsx `
            trust-contacts.csv trust-contacts.xlsx icb-contacts.csv icb-contacts.xlsx index.html 2>&1 |
            Out-File -FilePath $logFile -Append -Encoding utf8

        $salvageMsg = @"
[auto-salvage] Recover validated refresh data stranded by incomplete Claude session

The Claude session exited (code $claudeExit) without committing but left
validated changes on disk. The weekly-refresh bootstrap committed and pushed
them so the work is not lost. Derivatives were rebuilt from JSON and both URL
JSONs were confirmed to parse. Review the diff — if anything looks wrong, revert.

Co-Authored-By: Claude (weekly refresh bootstrap) <noreply@anthropic.com>
"@
        & git commit -m $salvageMsg 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
        $headAfter = & git rev-parse HEAD 2>$null

        if ($headBefore -ne $headAfter) {
            Write-Log "Auto-salvage commit created: $headBefore -> $headAfter."
            if ($env:GITHUB_TOKEN) {
                & git -c credential.helper= push "https://x-access-token:$($env:GITHUB_TOKEN)@github.com/Davewest84/nhs-trust-icb-data.git" main 2>&1 |
                    Out-File -FilePath $logFile -Append -Encoding utf8
                Write-Log "Auto-salvage push exit code: $LASTEXITCODE"
            } else {
                Write-Log "WARNING: GITHUB_TOKEN unavailable — salvage committed locally but NOT pushed."
            }
            $ErrorActionPreference = $savedEAP2
            "$(Get-Date -Format 'o') OK-SALVAGED $headAfter (claude exit=$claudeExit, log=$logFile)" | Out-File -FilePath $statusFile -Encoding utf8
            Send-Summary "OK-SALVAGED (Claude exit=$claudeExit)"
            # Fall through to log pruning + exit 0.
        } else {
            $ErrorActionPreference = $savedEAP2
            Write-Log "WARNING: salvage staged no committable change. Claude made no commit."
            "$(Get-Date -Format 'o') FAIL no-commit (claude exit=$claudeExit, log=$logFile)" | Out-File -FilePath $statusFile -Encoding utf8
            Send-Summary "FAIL no-commit"
            exit 2
        }
    } else {
        $ErrorActionPreference = $savedEAP2
        Write-Log "WARNING: HEAD unchanged and nothing on disk to salvage. Claude made no commit. (No URL changes + no contacts in this batch?)"
        "$(Get-Date -Format 'o') FAIL no-commit (claude exit=$claudeExit, log=$logFile)" | Out-File -FilePath $statusFile -Encoding utf8
        Send-Summary "FAIL no-commit"
        exit 2
    }
} else {
    Write-Log "OK: New commit created. HEAD moved $headBefore -> $headAfter"
    "$(Get-Date -Format 'o') OK $headAfter (log=$logFile)" | Out-File -FilePath $statusFile -Encoding utf8
    Send-Summary "OK"
}

# Prune old logs (keep last 12 weeks)
Get-ChildItem -Path $logDir -Filter "refresh-*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 12 |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit 0
