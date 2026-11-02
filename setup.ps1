# Rebuilds the full app: downloads the pre-event baseline, adds the files written during the event, applies the event changes to existing files.
param([string]$Out = (Join-Path $PSScriptRoot "agenticsales-full"))
$ErrorActionPreference = "Stop"
$BaselineUrl = "https://github.com/Abdulmalid/agenticsales-baseline.git"
$BaselineCommit = "e2ddc9c0213e571c3ea2edf3f42a016ccaae7194"

if (Test-Path $Out) { throw "$Out already exists; pass another folder: .\setup.ps1 -Out <folder>" }
git -c core.autocrlf=false clone --quiet $BaselineUrl $Out
git -C $Out checkout --quiet $BaselineCommit
Copy-Item -Path (Join-Path $PSScriptRoot "new\*") -Destination $Out -Recurse -Force
git -C $Out apply --whitespace=nowarn (Join-Path $PSScriptRoot "patches\event-changes.patch")
Write-Host "Done. The full app is in $Out (baseline $BaselineCommit + event work)."
