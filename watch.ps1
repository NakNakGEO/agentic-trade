param([string]$RunId = "replay2")

# Live view of a paper_trade run: progress, decisions, local-model activity, GPU.
$root = "D:\turic trading agent"
$progress = "$root\runs\backtest\$RunId\progress.log"
$memory = "$root\runs\backtest\$RunId\trading_memory.md"
$ollamaLog = "$env:LOCALAPPDATA\Ollama\server.log"
$begin = if (Test-Path $ollamaLog) { (Get-Item $ollamaLog).Length } else { 0 }
$started = Get-Date

function Read-NewLog {
    if (-not (Test-Path $ollamaLog)) { return "" }
    $stream = [System.IO.File]::Open($ollamaLog, 'Open', 'Read', 'ReadWrite')
    try {
        if ($stream.Length -lt $begin) { $script:begin = 0 }   # log was rotated
        $stream.Seek($begin, 'Begin') | Out-Null
        return (New-Object System.IO.StreamReader($stream)).ReadToEnd()
    } finally { $stream.Dispose() }
}

while ($true) {
    $text = Read-NewLog
    $requests = [regex]::Matches($text, 'init_sampler')
    $prompt = [regex]::Matches($text, 'init_sampler.*?text = (\d+)')
    $speed = [regex]::Matches($text, 'tg =\s+([\d.]+) t/s')
    $gpu = (& nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader 2>$null)

    Clear-Host
    "TradingAgents live view | run: $RunId | $(Get-Date -Format 'HH:mm:ss') | watching for $([int]((Get-Date) - $started).TotalMinutes) min"
    ("=" * 78)
    "PROGRESS"
    if (Test-Path $progress) { Get-Content $progress -Tail 6 } else { "  (waiting for the run to start)" }
    ""
    "DECISIONS SO FAR (date | ticker | rating | 5-day return | 5-day alpha)"
    if (Test-Path $memory) {
        $lines = Select-String -Path $memory -Pattern '^\[20' | ForEach-Object { $_.Line }
        if ($lines) { $lines | Select-Object -Last 14 } else { "  none yet" }
    } else { "  none yet" }
    ""
    "LOCAL MODEL (Ollama, gemma4)"
    "  LLM calls since this view opened : $($requests.Count)"
    if ($prompt.Count -gt 0) { "  last prompt size                  : $($prompt[$prompt.Count - 1].Groups[1].Value) tokens" }
    if ($speed.Count -gt 0) { "  last generation speed             : $($speed[$speed.Count - 1].Groups[1].Value) tokens/s" }
    "  GPU util, memory used, total      : $gpu"
    ""
    "(refreshes every 4 s; Ctrl-C closes this view and does not stop the run)"
    Start-Sleep -Seconds 4
}
