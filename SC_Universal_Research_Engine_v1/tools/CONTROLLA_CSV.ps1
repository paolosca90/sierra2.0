param([string]$SierraRoot='C:\SierraChart')
$p=Join-Path (Join-Path $SierraRoot 'Data') 'TO_REPLAY_NQ_TEST01.csv'
if(-not(Test-Path $p)){throw "Missing $p"}
$r=Import-Csv -LiteralPath $p
Write-Host ('Count: '+$r.Count)
$r|Group-Object kind|Select-Object Name,Count|Format-Table
$bars=@($r|Where-Object kind -EQ 'BAR_CLOSE')
Write-Host "Bars: $($bars.Count); first $($bars[0].bar_start); last $($bars[-1].bar_start)"
Write-Host "Unique signal bars: $(@($bars|Where-Object { (([int]$_.signal_mask) -band 3) -ne 0 }).Count)"
