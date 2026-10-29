# Same 9 pairs and dates as launch_fx9.ps1, decided by the local Gemma model (Ollama, thinking on) in one stream,
# so it can be watched live in the dashboard (?run=fx9_gemma). Safe to run again: finished cells are skipped.
param([string]$Run = "fx9_gemma", [string]$Start = "2026-09-15", [string]$End = "2026-09-24", [int]$Every = 3,
      [string]$Only = "")        # e.g. XAUUSD: a second process for just that pair, sharing the same run

$root = "D:\turic trading agent"
$py = "$root\TradingAgents\.venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"; $env:TRADINGAGENTS_NO_UPDATE_CHECK = "1"
New-Item -ItemType Directory -Force "$root\logs" | Out-Null

$pairs = "EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,NZDUSD,BTC-USD,ETH-USD,XAUUSD"
$argList = @("-W", "ignore", "-m", "paper_trade", "decide", "--tickers", $pairs, "--start", $Start, "--end", $End,
             "--every", "$Every", "--run-id", $Run, "--thinking")
$name = $Run
if ($Only) { $argList += @("--only", $Only); $name = "${Run}_$Only" }
$p = Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $root -WindowStyle Hidden -PassThru `
     -RedirectStandardOutput "$root\logs\$name.log" -RedirectStandardError "$root\logs\$name.err.log"
"$name $($p.Id)" | Add-Content "$root\logs\pids.txt"
"started $name (pid $($p.Id))"
