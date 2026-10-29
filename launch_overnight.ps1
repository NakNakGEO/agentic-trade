# Daily-decision comparison: local Gemma (thinking on) vs the Qwen API (thinking on, medium effort).
# Hidden, detached processes; safe to run again because finished cells are skipped.
param([string]$Which = "all",      # all | local | api
      [string]$Stream = "",        # restart just one stream by name, e.g. api_think_s2
      [string]$End = "2026-10-27") # last decision date; finished cells are skipped, so raising it just adds days

$root = "D:\turic trading agent"
$py = "$root\TradingAgents\.venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"; $env:TRADINGAGENTS_NO_UPDATE_CHECK = "1"
New-Item -ItemType Directory -Force "$root\logs" | Out-Null

$tickers = "AAPL,BTC-USD,EURUSD,XAUUSD"                   # one stock, one crypto, one forex pair, gold
$grid = @("--tickers", $tickers, "--start", "2026-10-12", "--end", $End, "--every", "1")
$apiArgs = @("--provider", "openai_compatible", "--backend-url", "https://api.iteracompute.com/v1",
             "--model", "qwen/qwen3.8-27b", "--effort", "medium", "--max-tokens", "8000")

function Start-Stream($name, $argList) {
    if ($Stream -and $Stream -ne $name) { return }
    $p = Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $root -WindowStyle Hidden -PassThru `
         -RedirectStandardOutput "$root\logs\$name.log" -RedirectStandardError "$root\logs\$name.err.log"
    "$name $($p.Id)" | Add-Content "$root\logs\pids.txt"
    "started $name (pid $($p.Id))"
    Start-Sleep -Seconds 20                      # stagger so streams do not collide on shared run files
}

if ($Which -in "all", "local") {
    Start-Stream "local_think" (@("-W", "ignore", "-m", "paper_trade", "decide") + $grid +
        @("--run-id", "daily_local_think", "--thinking"))
}
if ($Which -in "all", "api") {
    $shards = @("AAPL", "BTC-USD", "EURUSD", "XAUUSD")        # one asset per stream
    for ($i = 0; $i -lt $shards.Count; $i++) {
        Start-Stream "api_think_s$($i + 1)" (@("-W", "ignore", "-m", "paper_trade", "decide") + $grid +
            @("--run-id", "daily_api_think", "--only", $shards[$i]) + $apiArgs)
    }
}
