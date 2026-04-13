"""
Stark Labs — Structured JSON Logger
Shared by both Mark II Protocol and Iron Legion.
Writes newline-delimited JSON to logs/events.jsonl
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE = LOG_DIR / "events.jsonl"


def _ensure_log_dir():
    LOG_DIR.mkdir(exist_ok=True)


def log(event_type: str, **kwargs):
    """Append a structured log entry."""
    _ensure_log_dir()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "epoch": time.time(),
        "event": event_type,
        **kwargs,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    _print(entry)


def _print(entry: dict):
    if os.environ.get("STARK_LOG_STDOUT", "1") == "0":
        return
    tag = entry["event"].upper()
    detail_keys = [k for k in entry if k not in ("ts", "epoch", "event")]
    parts = [f"{k}={entry[k]}" for k in detail_keys]
    detail = "  " + " | ".join(parts) if parts else ""
    ts = entry["ts"][11:19]  # HH:MM:SS
    print(f"[{ts}] [{tag}]{detail}")


def get_log_path() -> str:
    return str(LOG_FILE)
