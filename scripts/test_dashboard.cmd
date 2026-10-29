@echo off
rem Test dashboard on port 8766: reads the LIVE system data read-only and keeps its own books. It never writes to the live folder.
set "AGENTIC_LIVE_DATA_DIR=D:\turic trading agent\runs"
cd /d "D:\agentic-trade-test"
"D:\agentic-trade-test\TradingAgents\.venv\Scripts\python.exe" -m paper_trade.dashboard --run live_gemma_short --port 8766
