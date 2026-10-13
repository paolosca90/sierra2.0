[CmdletBinding()]
param(
    [string]$SierraRoot='C:\SierraChart',
    [string]$LabRoot="$env:USERPROFILE\Documents\SC-OrderFlow-Lab",
    [string]$Symbol='NQZ26-CME',
    [switch]$ExploratoryAggregated,
    [int]$Trials=100
)
$ErrorActionPreference='Stop'
$lab=Join-Path $LabRoot 'universal-research-v1'
$python=Join-Path $lab '.venv\Scripts\python.exe'
$runner=Join-Path $lab 'tools\universal_tick_optimizer.py'
$scid=Join-Path (Join-Path $SierraRoot 'Data') "$Symbol.scid"
$signals=Join-Path (Join-Path $SierraRoot 'Data') 'TO_REPLAY_NQ_TEST01.csv'
$out=Join-Path $lab ('output\' + $Symbol + '_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
if(-not (Test-Path -LiteralPath $python)){throw "Run INSTALLA_E_PREPARA.ps1 first: $python"}
if(-not (Test-Path -LiteralPath $runner)){throw "Missing $runner"}
if(-not (Test-Path -LiteralPath $scid)){throw "Historical tape missing: $scid (check symbol under Sierra Chart Data)"}
if(-not (Test-Path -LiteralPath $signals)){throw "Collector CSV missing: $signals"}
$args_=@('--scid',$scid,'--signals',$signals,'--out',$out,
       '--tick','0.25','--tick-value','5','--commission','5',
       '--entry-slippage-ticks','1','--stop-slippage-ticks','1',
       '--exit-slippage-ticks','1','--limit-at-next-opposite',
       '--max-horizon-min','30','--trials',"$Trials")
if($ExploratoryAggregated){$args_+='--allow-aggregated-exploratory'}
Write-Host "DATA: $scid";Write-Host "SIGNALS: $signals";Write-Host "RESULTS: $out"
& $python $runner @args_
if($LASTEXITCODE -ne 0){throw "Stopped by safety/quality checks (exit $LASTEXITCODE). Do not mistake a partial result for a backtest."}
Write-Host "READ: $(Join-Path $out 'REPORT.md')" -ForegroundColor Green
