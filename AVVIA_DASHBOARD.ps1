[CmdletBinding()]
param([int]$Port=8765,[switch]$NoBrowser)
$ErrorActionPreference='Stop'
$project=Join-Path $PSScriptRoot 'SC_Universal_Research_Engine_v1'
$python=Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Ambiente Python mancante. Leggi README_DASHBOARD.md per la preparazione.' }
$savedUrlFile=Join-Path $project 'dashboard_url.txt'
if (-not $PSBoundParameters.ContainsKey('Port') -and (Test-Path -LiteralPath $savedUrlFile)) {
    $savedUrl=(Get-Content -LiteralPath $savedUrlFile -Raw).Trim()
    if ($savedUrl -match '^http://127\.0\.0\.1:(\d+)$') {
        try {
            $existing=Invoke-RestMethod "$savedUrl/api/bootstrap" -TimeoutSec 2
            if ($existing.version -eq '0.1-local') { if(-not $NoBrowser){Start-Process $savedUrl}; Write-Host "Dashboard: $savedUrl"; exit 0 }
        } catch {}
    }
}
$url="http://127.0.0.1:$Port"
try {
    $existing=Invoke-RestMethod "$url/api/bootstrap" -TimeoutSec 2
    if ($existing.version -eq '0.1-local') { if(-not $NoBrowser){Start-Process $url}; Write-Host "Dashboard: $url"; exit 0 }
} catch {}
for($attempt=0;$attempt -lt 30;$attempt++){
    $listener=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,$Port)
    try {$listener.Start();$listener.Stop();break}
    catch {$listener.Stop();$Port++}
}
$url="http://127.0.0.1:$Port"
$dashboard=Join-Path $project 'dashboard'
$log=Join-Path $project 'dashboard_server.log'
$err=Join-Path $project 'dashboard_server.error.log'
$arguments=@('-m','uvicorn','app:app','--app-dir',('"'+$dashboard+'"'),'--host','127.0.0.1','--port',"$Port")
$process=Start-Process -FilePath $python -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError $err
$process.Id | Set-Content (Join-Path $project 'dashboard_server.pid')
$ready=$false
for ($i=0;$i -lt 30;$i++) {
    Start-Sleep -Milliseconds 500
    try { $response=Invoke-RestMethod "$url/api/bootstrap" -TimeoutSec 2; if($response.version -eq '0.1-local'){$ready=$true;break} } catch {}
}
if(-not $ready){throw "Dashboard non avviata. Controlla $err"}
if(-not $NoBrowser){Start-Process $url}
$url | Set-Content (Join-Path $project 'dashboard_url.txt')
Write-Host "Dashboard: $url"
