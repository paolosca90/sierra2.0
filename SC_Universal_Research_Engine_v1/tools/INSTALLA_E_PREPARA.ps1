# RESEARCH ONLY. Never runs untrusted DLLs or sends trading orders.
# Run AFTER extracting full ZIP. Requires Internet for pinned GitHub sources and Python packages.
[CmdletBinding()]
param(
    [string]$SierraRoot = 'C:\SierraChart',
    [string]$LabRoot = "$env:USERPROFILE\Documents\SC-OrderFlow-Lab",
    [switch]$SkipRepos,
    [switch]$SkipPython
)
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$here=Split-Path -Parent $PSScriptRoot
$dst=Join-Path $LabRoot 'universal-research-v1'
$repos=Join-Path $LabRoot 'repos'
New-Item -ItemType Directory -Path $dst,$repos -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $here 'requirements.txt') -Destination (Join-Path $dst 'requirements.txt') -Force
foreach($folder in @('src','tools','config','tests','docs')) {
    Copy-Item -LiteralPath (Join-Path $here $folder) -Destination $dst -Recurse -Force
}
Write-Host "LAB: $dst"
$acs=Join-Path $SierraRoot 'ACS_Source'
if(-not (Test-Path -LiteralPath (Join-Path $acs 'sierrachart.h'))) {throw "Missing Sierra header at $acs"}
$universal=Join-Path $acs 'UniversalSignalTrader.cpp'
if(Test-Path -LiteralPath $universal) {
    $stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
    Copy-Item -LiteralPath $universal -Destination "$universal.backup_$stamp" -Force
}
Copy-Item -LiteralPath (Join-Path $dst 'src\UniversalSignalTrader.cpp') -Destination $universal -Force
Write-Host "ACSIL adapter staged: $universal"
function Import-Repo($slug,$commit,$directory) {
    $target=Join-Path $repos $directory
    if(Test-Path -LiteralPath $target) {
        Write-Host "Existing repo preserved: $target" -ForegroundColor Yellow
        return $target
    }
    $tmp=Join-Path $env:TEMP ("research_dl_" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    try {
        $zip=Join-Path $tmp 'source.zip'
        $extract=Join-Path $tmp 'unpacked'
        Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/$slug/zip/$commit" -OutFile $zip
        Expand-Archive -LiteralPath $zip -DestinationPath $extract
        $dirs=@(Get-ChildItem -LiteralPath $extract -Directory)
        if($dirs.Count -ne 1){throw "Unrecognized GitHub archive layout for $slug"}
        Move-Item -LiteralPath $dirs[0].FullName -Destination $target
        Set-Content -LiteralPath (Join-Path $target '_UPSTREAM_COMMIT.txt') -Value "$slug`n$commit" -Encoding Ascii
        Write-Host "Imported $slug at $commit"
    } finally {Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue}
    return $target
}
if(-not $SkipRepos) {
    $base=Import-Repo 'tanchekwei/SierraChartStrategyOptimizer' '3e1d466e97864f8bb107bca42b4733f0aed9a5dc' 'strategy-optimizer-upstream'
    $null=Import-Repo 'NickS785/SierraPy' '751137e750007d3411ca5afe6b8e9c6106b6d053' 'sierrapy-upstream'
    $null=Import-Repo 'drewautomates/optd-starter' '8f8fdff37115fd97bcc008e13c9960968fa5b64f' 'optd-starter-upstream'
    $opt=Join-Path $acs 'StrategyOptimizer_Universal'
    if(-not (Test-Path -LiteralPath $opt)) {
        Copy-Item -LiteralPath $base -Destination $opt -Recurse
        py -3 "$dst\tools\patch_optimizer.py" $opt
        if($LASTEXITCODE -ne 0){throw 'Optimizer patch rejected source version; originals remain intact'}
        Write-Host "Patched optimizer source: $opt"
    } else { Write-Host "Optimizer folder preserved: $opt" -ForegroundColor Yellow }
}
if(-not $SkipPython){
    py -3 -m venv (Join-Path $dst '.venv')
    $pip=Join-Path $dst '.venv\Scripts\python.exe'
    & $pip -m pip install -r (Join-Path $dst 'requirements.txt')
    if($LASTEXITCODE -ne 0){ throw 'pip dependencies failed' }
    & $pip -m unittest discover -s (Join-Path $dst 'tests') -p 'test_*.py' -v
    if($LASTEXITCODE -ne 0){ throw 'Internal tests FAILED' }
}
Write-Host 'SOURCE INSTALL COMPLETED. NO DLL BUILT. NO ORDERS PLACED.' -ForegroundColor Green
Write-Host 'NEXT: see LEGGIMI.md for ACSIL compilation and SCID check.'
