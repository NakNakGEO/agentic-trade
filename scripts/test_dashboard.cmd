@echo off
rem Test dashboard on port 8766: reads the LIVE system data read-only, keeps its own books. Never writes to the live folder.
set AGENTIC_LIVE_DATA_DIR=D:	uric trading agentuns
cd /d D:gentic-trade-test
"D:gentic-trade-test\TradingAgents\.venv\Scripts\python.exe" -m paper_trade.dashboard --run live_gemma_short --port 8766
