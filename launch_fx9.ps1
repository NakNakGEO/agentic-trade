# Paper trade the 7 forex majors, BTC, ETH and gold on a past window with the Qwen API, one hidden stream per pair.
# Safe to run again: finished cells are skipped. Restart one stream with -Stream <name>, e.g. fx9_api_EURUSD.
param([string]$Run = "fx9_api",
      [string]$Stream = "",
      [string]$Start = "2026-09-15",
      [string]$End = "2026-09-24",
      [int]$Every = 3)

$root = "D:\turic trading agent"
$py = "$root\TradingAgents\.venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"; $env:TRADINGAGENTS_NO_UPDATE_CHECK = "1"
New-Item -ItemType Directory -Force "$root\logs" | Out-Null

$pairs = @("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "BTC-USD", "ETH-USD", "XAUUSD")
$grid = @("--tickers", ($pairs -join ","), "--start", $Start, "--end", $End, "--every", "$Every")
$apiArgs = @("--provider", "openai_compatible", "--backend-url", "https://api.iteracompute.com/v1",
             "--model", "qwen/qwen3.8-27b", "--effort", "medium", "--max-tokens", "8000")

foreach ($pair in $pairs) {
    $name = "${Run}_$pair"
    if ($Stream -and $Stream -ne $name) { continue }
    $argList = @("-W", "ignore", "-m", "paper_trade", "decide") + $grid + @("--run-id", $Run, "--only", $pair) + $apiArgs
    $p = Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $root -WindowStyle Hidden -PassThru `
         -RedirectStandardOutput "$root\logs\$name.log" -RedirectStandardError "$root\logs\$name.err.log"
    "$name $($p.Id)" | Add-Content "$root\logs\pids.txt"
    "started $name (pid $($p.Id))"
    Start-Sleep -Seconds 25                      # stagger so streams do not collide on shared run files
}
