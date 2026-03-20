from __future__ import annotations

from datetime import datetime


def log_event(component: str, message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print("[{0}] [{1}] {2}".format(timestamp, component, message), flush=True)
