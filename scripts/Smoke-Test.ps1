# Run from a trusted checkout. This script uses only local simulated agents.
$ErrorActionPreference = "Stop"
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & py -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }
    & py -m ai_wakeup demo
    if ($LASTEXITCODE -ne 0) { throw "Simulation failed with exit code $LASTEXITCODE" }
    Write-Host "Local tests/simulation passed. This is not live-provider verification."
} finally {
    Pop-Location
}
