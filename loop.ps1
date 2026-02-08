param (
    [string]$Arg1,
    [string]$Arg2,
    [switch]$d  # Debug flag
)

$TotalStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$IterationTimings = @()
$LogFile = "bezi_performance.csv"
$DebugFlag = if ($d) { "-d" } else { "" }

# --- SELF-HEALING VENV LOGIC ---
$VenvPath = "$PSScriptRoot\.venv"
if (-not (Test-Path $VenvPath)) {
    py -m venv .venv
    & "$VenvPath\Scripts\Activate.ps1"
    python -m pip install --upgrade pip
    if (Test-Path "requirements.txt") { python -m pip install -r requirements.txt }
} else {
    & "$VenvPath\Scripts\Activate.ps1"
}

# --- IMPROVED ARGUMENT PARSING ---
$Mode = "build"
$PromptFile = "PROMPT_build.md"
$MaxIterations = 0

$ArgsList = @($Arg1, $Arg2)

foreach ($a in $ArgsList) {
    if ($a -eq "plan") {
        $Mode = "plan"
        $PromptFile = "PROMPT_plan.md"
    } elseif ($a -match '^\d+$') {
        $MaxIterations = [int]$a
    }
}

$CurrentBranch = git branch --show-current

# Visual Status Box
Write-Host "------------------------------------------------" -ForegroundColor Cyan
Write-Host "| MODE:   $($Mode.PadRight(36)) |" -ForegroundColor Cyan
Write-Host "| DEBUG:  $($d.ToString().PadRight(36)) |" -ForegroundColor Cyan
Write-Host "| PROMPT: $($PromptFile.PadRight(36)) |" -ForegroundColor Cyan
Write-Host "| BRANCH: $($CurrentBranch.PadRight(36)) |" -ForegroundColor Cyan
Write-Host "| ITER:   $($MaxIterations.ToString().PadRight(36)) |" -ForegroundColor Cyan 
Write-Host "------------------------------------------------" -ForegroundColor Cyan

if (-not (Test-Path $PromptFile)) { Write-Error "Error: $PromptFile not found"; exit 1 }

# Init the Bezi Bridge with proper ArgumentList array
$InitArgs = if ($d) { @("bezi_bridge.py", "--init", "-d") } else { @("bezi_bridge.py", "--init") }
Start-Process -FilePath "py" -ArgumentList $InitArgs -NoNewWindow -Wait

$Iteration = 0
$TempPromptPath = Join-Path $env:TEMP "bezi_prompt_tmp.md"

try {
    while ($true) {
        if ($MaxIterations -gt 0 -and $Iteration -ge $MaxIterations) { break }

        $LoopTimer = [System.Diagnostics.Stopwatch]::StartNew()
        
        # Pass the prompt via file
        Get-Content -Path $PromptFile -Raw | Out-File -FilePath $TempPromptPath -Encoding utf8
        
        # Build Bridge Arguments as an array to fix malformed string errors
        $BridgeArgs = @("bezi_bridge.py", $TempPromptPath)
        if ($d) { $BridgeArgs += "-d" }
        
        # Execute Bridge
        Start-Process -FilePath "py" -ArgumentList $BridgeArgs -NoNewWindow -Wait
        
        # Check if the bridge succeeded before continuing loop
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Bridge failed with exit code $LASTEXITCODE. Stopping loop." -ForegroundColor Red
            break
        }
        
        $LoopTimer.Stop()
        $Iteration++
        
        $Seconds = [Math]::Round($LoopTimer.Elapsed.TotalSeconds, 2)
        $IterationTimings += [PSCustomObject]@{
            Timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            Mode      = $Mode
            Iteration = $Iteration
            Duration  = $Seconds
        }

        Write-Host "`n--- LOOP $Iteration COMPLETED IN $($Seconds)s ---`n" -ForegroundColor Green
    }
}
finally {
    $TotalStopwatch.Stop()
    $TotalMin = [Math]::Round($TotalStopwatch.Elapsed.TotalMinutes, 2)
    
    # Final Timing Report
    Write-Host "`n----------------- EXECUTION REPORT ----------------" -ForegroundColor Yellow
    foreach ($entry in $IterationTimings) {
        $Label = "Loop $($entry.Iteration)"
        Write-Host "| $($Label.PadRight(10)) : $($entry.Duration.ToString().PadRight(32))s |" -ForegroundColor Yellow
    }
    Write-Host "|-----------------------------------------------|" -ForegroundColor Yellow
    Write-Host "| TOTAL TIME : $($TotalMin.ToString().PadRight(31)) min |" -ForegroundColor Yellow
    Write-Host "-------------------------------------------------" -ForegroundColor Yellow

    if ($IterationTimings.Count -gt 0) {
        $IterationTimings | Export-Csv -Path $LogFile -NoTypeInformation -Append
    }

    if (Test-Path $TempPromptPath) { Remove-Item $TempPromptPath }
    Write-Host "Execution Finished." -ForegroundColor Yellow
}