@echo off
rem Test dashboard on port 8766 with the call schedule switched on (to see the pace line). Reads the LIVE data read-only; never writes to the live folder.
set "AGENTIC_LIVE_DATA_DIR=D:\turic trading agent\runs"
set "AGENTIC_CALL_EVERY_GEMMA_SHORT=60"
cd /d "D:\agentic-trade-test"
"D:\agentic-trade-test\TradingAgents\.venv\Scripts\python.exe" -m paper_trade.dashboard --run live_gemma_short --port 8766
