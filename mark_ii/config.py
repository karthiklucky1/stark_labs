from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

MARK_II_DIR = Path(__file__).resolve().parent
ROOT_DIR = MARK_II_DIR.parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY")

OPENAI_PATCH_MODEL = os.environ.get("OPENAI_PATCH_MODEL", "gpt-5.4-2026-03-05")
ANTHROPIC_PATCH_MODEL = os.environ.get("ANTHROPIC_PATCH_MODEL", "claude-sonnet-4-20250514")
DEEPSEEK_PATCH_MODEL = os.environ.get("DEEPSEEK_PATCH_MODEL", "deepseek-reasoner")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

MAX_MARKS = 7
MARK_NAMES = ["I", "II", "III", "IV", "V", "VI", "VII"]
PATCH_MEMORY_FILE = MARK_II_DIR / "patch_memory.json"
TASK_SPECS_DIR = MARK_II_DIR / "task_specs"
DEFAULT_TASK_SPEC_FILE = TASK_SPECS_DIR / "payment_api.json"

PORT = int(os.environ.get("MARK_II_PORT", "8111"))
BASE_URL = os.environ.get("MARK_II_BASE_URL", f"http://127.0.0.1:{PORT}")

SERVER_READY_RETRIES = int(os.environ.get("MARK_II_READY_RETRIES", "20"))
SERVER_READY_INTERVAL_S = float(os.environ.get("MARK_II_READY_INTERVAL_S", "0.5"))
SMOKE_TIMEOUT_S = float(os.environ.get("MARK_II_SMOKE_TIMEOUT_S", "5.0"))
SWARM_TIMEOUT_S = float(os.environ.get("MARK_II_SWARM_TIMEOUT_S", "30.0"))
VALIDATION_MODE = os.environ.get("MARK_II_VALIDATION_MODE", "asgi")
ASGI_BASE_URL = os.environ.get("MARK_II_ASGI_BASE_URL", "http://markii.local")
