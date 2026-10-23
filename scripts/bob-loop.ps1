param(
    [string]$ProjectDir = (Get-Location).Path,
    [string]$Feature = "",
    [int]$MaxIterations = 20
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $ProjectDir

$logDir = Join-Path $ProjectDir ".bob\loop-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$hasState = Test-Path -LiteralPath (Join-Path $ProjectDir ".bob\run-state.yaml")
$result = "failed"
$reason = "max iterations ($MaxIterations) reached"

for ($i = 1; $i -le $MaxIterations; $i++) {
    if (-not $hasState -and $Feature -ne "" -and $i -eq 1) {
        $escaped = $Feature.Replace('"', "'")
        $prompt = "/bob-pipeline:bob-run `"$escaped`" --night --one-slice"
    } else {
        $prompt = "/bob-pipeline:bob-run --resume --night --one-slice"
    }

    $log = Join-Path $logDir ("iter-{0:D2}.log" -f $i)
    Write-Host ("[bob-loop] iteration {0}/{1}: {2}" -f $i, $MaxIterations, $prompt)

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & claude -p $prompt --permission-mode bypassPermissions 2>&1 | ForEach-Object { "$_" }
    $ErrorActionPreference = $prevEap
    $output | Set-Content -LiteralPath $log -Encoding UTF8

    $line = $output | Where-Object { $_ -match '^\s*BOB-LOOP:\s*(next|done|failed)\s*$' } | Select-Object -Last 1
    if (-not $line) {
        $result = "failed"
        $reason = "no BOB-LOOP line in $log"
        break
    }
    $status = ($line -replace '^\s*BOB-LOOP:\s*', '').Trim()
    Write-Host ("[bob-loop] iteration {0} -> {1}" -f $i, $status)
    if ($status -eq "next") { continue }
    $result = $status
    $reason = ""
    break
}

Write-Host ("BOB-LOOP-DRIVER: {0} {1}" -f $result, $reason)
if ($result -eq "done") { exit 0 } else { exit 1 }
