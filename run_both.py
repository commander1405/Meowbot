#!/usr/bin/env python3
"""
اجرای هم‌زمان MeowBot (بله) + MEGA BOT (روبیکا)

Railway / یک کانتینر:
  Start Command → python run_both.py

هر ربات پروسس جدا دارد؛ کرش یکی لزوماً دیگری را نمی‌کشد.
لاگ‌ها با پیشوند [BALE] و [RUBIKA] مشخص می‌شوند.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

# اگر بخواهی فقط یکی را اجرا کنی:
#   RUN_BALE=0  یا  RUN_RUBIKA=0
RUN_BALE = os.getenv("RUN_BALE", "1") not in ("0", "false", "False")
RUN_RUBIKA = os.getenv("RUN_RUBIKA", "1") not in ("0", "false", "False")


def _popen(name: str, args: list[str]) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    print(f"[launcher] starting {name}: {' '.join(args)}", flush=True)
    return subprocess.Popen(
        args,
        cwd=str(ROOT),
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def main() -> None:
    procs: dict[str, subprocess.Popen] = {}

    if RUN_BALE:
        procs["bale"] = _popen("MeowBot-Bale", [PYTHON, "main.py"])
    else:
        print("[launcher] Bale disabled (RUN_BALE=0)", flush=True)

    if RUN_RUBIKA:
        procs["rubika"] = _popen(
            "MEGA-Rubika",
            [PYTHON, "-m", "mega_rubika.main"],
        )
    else:
        print("[launcher] Rubika disabled (RUN_RUBIKA=0)", flush=True)

    if not procs:
        print("[launcher] nothing to run", flush=True)
        sys.exit(1)

    stopping = False

    def _stop(signum, frame):
        nonlocal stopping
        if stopping:
            return
        stopping = True
        print(f"[launcher] signal {signum} — stopping children…", flush=True)
        for name, p in procs.items():
            if p.poll() is None:
                try:
                    p.send_signal(signal.SIGTERM)
                except Exception as e:
                    print(f"[launcher] kill {name}: {e}", flush=True)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # مانیتور: اگر یکی مرد، لاگ بده؛ اختیاری ری‌استارت ساده برای روبیکا
    restart_count = {"rubika": 0}
    max_restart = int(os.getenv("RUBIKA_MAX_RESTART", "20"))

    while not stopping:
        time.sleep(2)
        dead = [n for n, p in list(procs.items()) if p.poll() is not None]
        for name in dead:
            code = procs[name].returncode
            print(f"[launcher] process '{name}' exited code={code}", flush=True)
            if name == "rubika" and not stopping and restart_count["rubika"] < max_restart:
                restart_count["rubika"] += 1
                wait = min(30, 2 * restart_count["rubika"])
                print(
                    f"[launcher] restart rubika in {wait}s "
                    f"({restart_count['rubika']}/{max_restart})",
                    flush=True,
                )
                time.sleep(wait)
                if stopping:
                    break
                procs["rubika"] = _popen(
                    "MEGA-Rubika",
                    [PYTHON, "-m", "mega_rubika.main"],
                )
            elif name == "bale":
                # بله قلب سیستم است؛ اگر مرد کل لانچر خارج شود تا Railway ری‌استارت کند
                print("[launcher] Bale died — exiting so platform restarts", flush=True)
                _stop(signal.SIGTERM, None)
                break
            else:
                del procs[name]

        if not procs:
            break
        if all(p.poll() is not None for p in procs.values()):
            break

    for name, p in procs.items():
        if p.poll() is None:
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
    print("[launcher] done", flush=True)


if __name__ == "__main__":
    main()
