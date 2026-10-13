# Visual Studio 2022/2026 Desktop development with C++ required. No downloads, no untrusted binary.
[CmdletBinding()]
param([string]$SierraRoot='C:\SierraChart')
$ErrorActionPreference='Stop'
$repo=Join-Path $SierraRoot 'ACS_Source\StrategyOptimizer_Universal'
$data=Join-Path $SierraRoot 'Data'
if(-not (Test-Path -LiteralPath (Join-Path $repo 'StrategyOptimizer.cpp'))){throw "Missing optimizer sources: $repo"}
$vswhere="${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if(-not (Test-Path -LiteralPath $vswhere)){throw 'Visual Studio Installer / vswhere.exe missing. Install Visual Studio Build Tools C++.'}
$vsRoot=& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if(-not $vsRoot){throw 'Visual Studio Desktop Development C++ toolchain missing'}
$vcvars=Join-Path $vsRoot 'VC\Auxiliary\Build\vcvarsall.bat'
if(-not (Test-Path -LiteralPath $vcvars)){throw "MSVC vcvarsall not found: $vcvars"}
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$out=Join-Path $data "StrategyOptimizer_Universal_$stamp.dll"
$src=@('StrategyOptimizer.cpp','ResultAnalyzer.cpp','ReplayManager.cpp','OnChartLogging.cpp','Logging.cpp','ConfigManager.cpp','StrategyOptimizerHelpers.cpp','CombinationGenerator.cpp','InputParameter.cpp','ReportGenerator.cpp')
$compile=($src | ForEach-Object { '"' + (Join-Path $repo $_) + '"' }) -join ' '
# Compile in the source directory so ../sierrachart.h is unambiguous.
$cmd="call `"$vcvars`" amd64 && cl /nologo /LD /MT /EHsc /std:c++17 /O2 /W3 $compile /link Gdi32.lib User32.lib Shell32.lib /DLL /OUT:`"$out`""
Push-Location $repo
try { cmd.exe /D /C $cmd; if($LASTEXITCODE -ne 0){throw "MSVC build failed, exit $LASTEXITCODE"} }
finally { Pop-Location }
if(-not (Test-Path -LiteralPath $out)){throw 'Expected DLL does not exist'}
Write-Host "DLL built locally: $out" -ForegroundColor Green
Write-Host 'Use Analysis > Studies > Add Custom Study, find Strategy Optimizer.'
