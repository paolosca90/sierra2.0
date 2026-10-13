[CmdletBinding()]
param([string]$SierraRoot='C:\SierraChart')
$ErrorActionPreference='Stop'
$project=Split-Path $PSScriptRoot -Parent
$workspace=Split-Path $project -Parent
$vswhere="${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'MSVC Build Tools not found.' }
$vsRoot=& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsRoot) { throw 'MSVC C++ toolchain missing.' }
$vcvars=Join-Path $vsRoot 'VC\Auxiliary\Build\vcvarsall.bat'
$build=Join-Path $project 'build_v2'
New-Item -ItemType Directory -Path $build -Force | Out-Null
$include=Join-Path $SierraRoot 'ACS_Source'
$sources=@(
    @{Path=(Join-Path $workspace 'TO_Deluxe_Levels.cpp'); Name='TO_Deluxe_Levels_Causal'},
    @{Path=(Join-Path $project 'src\ResearchCollectorV2.cpp'); Name='ResearchCollectorV2'}
)
Push-Location $build
try {
    foreach ($source in $sources) {
        $dll=Join-Path $build ($source.Name+'.dll')
        $command='call "'+$vcvars+'" amd64 && cl /nologo /LD /MT /EHsc /std:c++17 /O2 /W3 /I"'+$include+'" "'+$source.Path+'" /link Gdi32.lib User32.lib /DLL /OUT:"'+$dll+'"'
        & cmd.exe /D /C $command
        if ($LASTEXITCODE -ne 0) { throw "Build failed: $($source.Name)" }
    }
}
finally { Pop-Location }
Write-Host "DLL compiled in $build. Not installed in Sierra; no chart or trading changes."
