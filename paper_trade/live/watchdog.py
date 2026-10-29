"""Keeps the live loops (and, if asked, the dashboard) running: ``python -m paper_trade watchdog``.

Run it on a schedule (see scripts/install_watchdog_task.ps1). Each run looks at the processes on the machine:
a loop that is not running is started; a loop that is running but has not saved its book for STALE_SECONDS is
treated as hung, killed and started again. Nothing is done for a loop that is healthy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from paper_trade import config
from paper_trade.live import settings

STALE_SECONDS = 600                         # a loop saves its book every minute; ten minutes of silence is a hang
DASHBOARD_RUN = "live_gemma_short"
DASHBOARD_PORT = 8765
DETACHED = 0x08000000 | 0x00000008 | 0x00000200      # no window, not tied to this process, its own process group
LIST_PROCESSES = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" "
                  "| Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress")


@dataclass(frozen=True)
class Process:
    pid: int
    command: str


def parse_processes(text: str) -> list[Process]:
    """The PowerShell listing (one object or a list, or nothing) as processes."""
    text = text.strip()
    if not text:
        return []
    data = json.loads(text)
    data = data if isinstance(data, list) else [data]
    return [Process(int(row["ProcessId"]), row.get("CommandLine") or "") for row in data]


def running_processes() -> list[Process]:
    done = subprocess.run(["powershell", "-NoProfile", "-Command", LIST_PROCESSES], capture_output=True, text=True, timeout=60)
    return parse_processes(done.stdout)


def loop_pids(processes: list[Process], account: str) -> list[int]:
    """Every process running this account's loop (the venv launcher and the real Python both show it)."""
    needle = f"paper_trade live --account {account} loop"
    return [p.pid for p in processes if needle in p.command]


def dashboard_running(processes: list[Process]) -> bool:
    return any("paper_trade.dashboard" in p.command for p in processes)


def book_age(account: settings.Account, now: float | None = None) -> float | None:
    """Seconds since the account's book was last saved, or None when it has never been."""
    try:
        return (now or time.time()) - settings.book_path(account).stat().st_mtime
    except OSError:
        return None


def plan(processes: list[Process], ages: dict[str, float | None], stale: float = STALE_SECONDS) -> dict:
    """What to do for each account: ``ok``, ``start`` (not running) or ``restart`` (running but hung)."""
    actions = {}
    for name in settings.ACCOUNTS:
        pids = loop_pids(processes, name)
        age = ages.get(name)
        actions[name] = "start" if not pids else "restart" if age is not None and age > stale else "ok"
    return actions


def _launch(arguments: list[str], log: Path, error_log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out, open(error_log, "ab") as err:
        return subprocess.Popen([sys.executable, *arguments], cwd=config.ROOT, stdout=out, stderr=err, creationflags=DETACHED).pid


def start_loop(name: str) -> int:
    logs = config.ROOT / "logs"
    pid = _launch(["-W", "ignore", "-m", "paper_trade", "live", "--account", name, "loop"],
                  logs / f"live_loop_{name}.log", logs / f"live_loop_{name}.err.log")
    with open(logs / "pids.txt", "a", encoding="utf-8") as handle:
        handle.write(f"live_loop_{name} {pid}\n")
    return pid


def start_dashboard() -> int:
    logs = config.ROOT / "logs"
    return _launch(["-m", "paper_trade.dashboard", "--run", DASHBOARD_RUN, "--port", str(DASHBOARD_PORT)],
                   logs / "dashboard.log", logs / "dashboard.err.log")


def kill(pids: list[int]) -> None:
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)


def check(dashboard: bool = False, dry_run: bool = False, stale: float = STALE_SECONDS) -> list[str]:
    """One pass: fix what needs fixing and say what was done (one line per action)."""
    if config.IS_TEST_COPY or config.READ_ONLY_DATA:
        return ["this is a test copy: it never starts or stops the live loops, so the watchdog does nothing here"]
    processes = running_processes()
    ages = {name: book_age(account) for name, account in settings.ACCOUNTS.items()}
    said = []
    for name, action in plan(processes, ages, stale).items():
        if action == "ok":
            continue
        said.append(f"{name}: {action}{' (dry run)' if dry_run else ''}")
        if dry_run:
            continue
        if action == "restart":
            kill(loop_pids(processes, name))
        said[-1] += f" -> pid {start_loop(name)}"
    if dashboard and not dashboard_running(processes):
        said.append(f"dashboard: start{' (dry run)' if dry_run else ''}")
        if not dry_run:
            said[-1] += f" -> pid {start_dashboard()}"
    return said


def add_arguments(sub) -> None:
    watchdog = sub.add_parser("watchdog", help="start any live loop that is not running or has stopped saving (run it on a schedule)")
    watchdog.add_argument("--dashboard", action="store_true", help="also start the dashboard if it is not running")
    watchdog.add_argument("--dry-run", action="store_true", help="only say what would be done")
    watchdog.add_argument("--stale-seconds", type=float, default=STALE_SECONDS)


def run(args) -> int:
    for line in check(args.dashboard, args.dry_run, args.stale_seconds) or ["all loops healthy"]:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}", flush=True)
    return 0
