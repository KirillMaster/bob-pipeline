param(
    [string]$ProjectDir = (Get-Location).Path,
    [string]$Feature = "",
    [int]$MaxIterations = 20
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Set-Location -LiteralPath $ProjectDir

$logDir = Join-Path $ProjectDir ".bob\loop-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$statePath = Join-Path $ProjectDir ".bob\run-state.yaml"
if (-not (Test-Path -LiteralPath $statePath) -and $Feature -eq "") {
    Write-Host "BOB-LOOP-DRIVER: failed no run state ($statePath) and no -Feature given; pass -Feature `"<description>`" to start a run"
    exit 1
}

$result = "failed"
$reason = "max iterations ($MaxIterations) reached"
$retried = $false

for ($i = 1; $i -le $MaxIterations; $i++) {
    $hasState = Test-Path -LiteralPath $statePath
    if (-not $hasState) {
        $escaped = $Feature.Replace('"', "'")
        $prompt = "/bob-pipeline:bob-run `"$escaped`" --night --one-slice"
    } else {
        $prompt = "/bob-pipeline:bob-run --resume --night --one-slice"
    }

    $log = Join-Path $logDir ("iter-{0:D2}.log" -f $i)
    Write-Host ("[bob-loop] iteration {0}/{1}: {2}" -f $i, $MaxIterations, $prompt)

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = $prompt | & claude -p --permission-mode bypassPermissions 2>&1 | ForEach-Object { "$_" }
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    $output | Set-Content -LiteralPath $log -Encoding UTF8

    if ($exitCode -ne 0) {
        $result = "failed"
        $reason = "claude exited $exitCode in $log"
        break
    }

    $line = $output | Where-Object { $_ -match '^\s*BOB-LOOP:\s*(next|done|failed)\s*$' } | Select-Object -Last 1
    if (-not $line) {
        if (-not $retried) {
            $retried = $true
            Write-Host ("[bob-loop] iteration {0}: no BOB-LOOP line, retrying once" -f $i)
            continue
        }
        $result = "failed"
        $reason = "no BOB-LOOP line after retry in $log"
        break
    }
    $retried = $false
    $status = ($line -replace '^\s*BOB-LOOP:\s*', '').Trim()
    Write-Host ("[bob-loop] iteration {0} -> {1}" -f $i, $status)
    if ($status -eq "next") { continue }
    $result = $status
    $reason = ""
    break
}

Write-Host ("BOB-LOOP-DRIVER: {0} {1}" -f $result, $reason)
if ($result -eq "done") { exit 0 } else { exit 1 }
