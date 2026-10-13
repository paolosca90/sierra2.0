[CmdletBinding()]
param(
    [ValidateSet('NQ','ES')][string]$Instrument='NQ',
    [string]$Symbol='NQZ26-CME',
    [string]$Signals='C:\SierraChart\Data\TO_REPLAY_NQ_TEST01.csv',
    [string]$SierraRoot='C:\SierraChart',
    [string]$Python="$env:USERPROFILE\Documents\SC-OrderFlow-Lab\universal-research-v1\.venv\Scripts\python.exe",
    [string]$ChartTimezone='America/New_York',
    [double]$Commission=5.0,
    [int]$Trials=200
)
$ErrorActionPreference='Stop'
$project=Split-Path $PSScriptRoot -Parent
$runner=Join-Path $PSScriptRoot 'robust_optimizer.py'
$tape=Join-Path $SierraRoot "Data\$Symbol.scid"
$result=Join-Path $project ('output\'+$Symbol+'_v2_'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
if (-not (Test-Path -LiteralPath $Python)) { throw 'Specify -Python pointing to a Python environment with requirements.txt installed.' }
& $Python $runner --scid $tape --signals $Signals --instrument $Instrument --chart-timezone $ChartTimezone --commission $Commission --trials $Trials --out $result
if ($LASTEXITCODE -ne 0) { throw 'Research failed. Read error; do not use partial results.' }
Write-Host "Report: $result\REPORT.md"
