#!/usr/bin/env python3
# tg_codex_gateway.py
# Telegram -> Talker Looper gateway
#
# Behavior:
#   - Echo ALL incoming text messages to the console.
#   - Bot commands (start with /) are handled by this script.
#   - Any non-command text is forwarded to the CURRENT agent (default: "looper").
#
# Looper behavior:
#   1) Gateway writes a prompt file into Talker inbox using atomic rename:
#      temp file -> Prompt_YYYY_MM_DD_HH_MM_SS_mmm(.suffix).md
#   2) Looper processes prompt and appends events to Prompt_..._Result.md
#   3) Background worker polls all result files and delivers new events to Telegram.
#
# Setup:
#   1) Create a bot with @BotFather and get TELEGRAM_BOT_TOKEN
#   2) Discover your chat_id: set ALLOWED_CHAT_ID=0, run script, send /id
#   3) Set env vars:
#        - TELEGRAM_BOT_TOKEN
#        - ALLOWED_CHAT_ID   (your numeric chat_id)
#   4) Start with Talker root parameter:
#        python tg_codex_gateway.py C:\CorrisBot\Talker
#   5) Ensure Looper launcher exists (StartLoopsInWT.bat) and Codex login is valid
#
# Telegram commands:
#   /id                 -> show your chat_id
#   /agent              -> show current gateway/looper state
#   /setagent <name>    -> set current agent (supported: looper)
#   /reset_session      -> reset current sender queue/session
#   /reset_all          -> reset all sender queues
#   /reset              -> alias of /reset_session
#   /new_session        -> alias of /reset_session
#   /loginstatus        -> show Codex login status
#   /console            -> show current console output mode
#   /setconsole <mode>  -> set console mode: quiet (default) or full
#   /toggleconsole      -> toggle between quiet and full console mode
#   /show_reasoning     -> show/hide [reasoning] stream (on|off)
#   /show_commands      -> show/hide [command] stream (on|off)
#   /routing ...        -> pass routing control command to Talker
#   /help               -> list all available bot commands
#
# SECURITY:
#   Only ALLOWED_CHAT_ID can run agent commands (plain text forwarding,
#   /setagent, /reset*, /routing).
#   /id is allowed for everyone (so you can discover chat_id), but is still echoed to console.

import os
import sys
import json
import time
import uuid
import hashlib
import argparse
import atexit
import asyncio
import re
import shutil
import subprocess
import threading
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Import agent runners for result parsing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Looper'))
from agent_runners import CodexRunner, KimiRunner

# --- Single instance lock ---
_LOCK_FILE = os.path.join(os.getcwd(), ".gateway.lock")

def _check_single_instance():
  """Ensure only one gateway instance is running."""
  if os.path.exists(_LOCK_FILE):
    try:
      with open(_LOCK_FILE, "r") as f:
        old_pid = int(f.read().strip())
      # Check if process still exists (Windows-compatible)
      try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(1, False, old_pid)  # PROCESS_TERMINATE = 1
        if handle:
          kernel32.CloseHandle(handle)
          print(f"[ERROR] Gateway already running (PID {old_pid})")
          print(f"[ERROR] Remove {_LOCK_FILE} if process is dead.")
          sys.exit(1)
      except Exception:
        pass
    except (ValueError, IOError):
      pass
    # Stale lock file, remove it
    try:
      os.remove(_LOCK_FILE)
    except Exception:
      pass
  
  # Create lock file with our PID
  with open(_LOCK_FILE, "w") as f:
    f.write(str(os.getpid()))

def _release_lock():
  """Release the lock on exit."""
  try:
    if os.path.exists(_LOCK_FILE):
      with open(_LOCK_FILE, "r") as f:
        pid = int(f.read().strip())
      if pid == os.getpid():
        os.remove(_LOCK_FILE)
  except Exception:
    pass

# Check and register cleanup
_check_single_instance()
atexit.register(_release_lock)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.environ.get("ALLOWED_CHAT_ID", "").strip()

if not TOKEN:
  raise SystemExit("Missing TELEGRAM_BOT_TOKEN env var")
if not ALLOWED_CHAT_ID:
  raise SystemExit("Missing ALLOWED_CHAT_ID env var")

try:
  ALLOWED_CHAT_ID_INT = int(ALLOWED_CHAT_ID)
except ValueError:
  raise SystemExit("ALLOWED_CHAT_ID must be an integer")

# --- Runtime agent mode ---
_CURRENT_AGENT = "looper"

# --- Session persistence for gateway logging ---
_SESSION_DIR = os.path.join(os.getcwd(), "sessions")
_CURRENT_SESSION_DIR = None  # Path to current active session directory (gateway logs)
_TEMP_DIR = os.path.join(os.getcwd(), "_Temp")

def _ensure_session_dir():
  """Create sessions directory if it doesn't exist."""
  try:
    os.makedirs(_SESSION_DIR, exist_ok=True)
  except Exception:
    pass

def _get_latest_session_dir() -> Optional[str]:
  """Get the most recent session directory path, or None if no sessions exist."""
  try:
    if os.path.isdir(_SESSION_DIR):
      # List all session directories
      dirs = [d for d in os.listdir(_SESSION_DIR) 
              if d.startswith("session_") and os.path.isdir(os.path.join(_SESSION_DIR, d))]
      if dirs:
        # Sort by name (timestamp) to get latest
        dirs.sort()
        return os.path.join(_SESSION_DIR, dirs[-1])
  except Exception:
    pass
  return None

def _get_git_version() -> str:
  """Get git commit hash if available, else 'unknown'."""
  try:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], 
                           capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
      return result.stdout.strip()
  except Exception:
    pass
  return "unknown"

def _create_new_session_dir():
  """Create a new session directory (gateway operational logs)."""
  global _CURRENT_SESSION_DIR
  try:
    _ensure_session_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_name = f"session_{timestamp}"
    _CURRENT_SESSION_DIR = os.path.join(_SESSION_DIR, session_name)
    os.makedirs(_CURRENT_SESSION_DIR, exist_ok=True)
    # Create metadata file with rich info
    with open(os.path.join(_CURRENT_SESSION_DIR, "meta.txt"), "w", encoding="utf-8") as f:
      f.write(f"timestamp: {timestamp}\n")
      f.write(f"version: {_get_git_version()}\n")
      f.write(f"workdir: {os.getcwd()}\n")
      f.write(f"allowed_chat_id: {ALLOWED_CHAT_ID}\n")
      f.write(f"agent: {_CURRENT_AGENT}\n")
      f.write(f"console_mode: {_CONSOLE_MODE}\n")
      f.write(f"looper_root: {_LOOPER_ROOT}\n")
      f.write(f"talker_root: {_TALKER_ROOT}\n")
  except Exception as e:
    print(f"[WARN] Failed to create session directory: {e}")
    _CURRENT_SESSION_DIR = None

def _get_session_log_paths() -> Tuple[Optional[str], Optional[str]]:
  """Get stdout and stderr log paths for current session."""
  if _CURRENT_SESSION_DIR:
    stdout_path = os.path.join(_CURRENT_SESSION_DIR, "stdout.log")
    stderr_path = os.path.join(_CURRENT_SESSION_DIR, "stderr.log")
    return stdout_path, stderr_path
  return None, None

def _ensure_temp_dir():
  try:
    os.makedirs(_TEMP_DIR, exist_ok=True)
  except Exception:
    pass

# --- Looper/Talker configuration ---
_LOOPER_ROOT = os.environ.get("LOOPER_ROOT", r"C:\CorrisBot\Looper").strip() or r"C:\CorrisBot\Looper"
_TALKER_ROOT = ""
_TALKER_INBOX_ROOT = ""
_START_LOOPS_BAT = os.path.join(_LOOPER_ROOT, "StartLoopsInWT.bat")
_SENDER_ID_OVERRIDE = os.environ.get("TALKER_SENDER_ID", "").strip()
_SKIP_TALKER_BOOT = os.environ.get("GATEWAY_SKIP_TALKER_BOOT", "").strip().lower() in ("1", "true", "yes", "on")

# Polling model (same style as looper: lightweight polling, no watchdog).
_RESULT_POLL_ACTIVE_SEC = float(os.environ.get("RESULT_POLL_ACTIVE_SEC", "0.25"))
_RESULT_POLL_IDLE_SEC = float(os.environ.get("RESULT_POLL_IDLE_SEC", "0.75"))

_PROMPT_TIMESTAMP_RE = re.compile(
  r"^(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})_"
  r"(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})_"
  r"(?P<millis>\d{3})(?:_(?P<suffix>[A-Za-z0-9]+))?$"
)

_TALKER_LOOPER_STARTED = False

def _parse_runtime_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="Telegram gateway for Talker looper"
  )
  parser.add_argument(
    "talker_root",
    help="Path to Talker root folder (contains Prompts/Inbox)",
  )
  return parser.parse_args()

def _configure_talker_paths(talker_root: str):
  global _TALKER_ROOT, _TALKER_INBOX_ROOT
  root = os.path.abspath((talker_root or "").strip())
  if not root:
    raise SystemExit("Missing required argument: talker_root")
  _TALKER_ROOT = root
  _TALKER_INBOX_ROOT = os.path.join(_TALKER_ROOT, "Prompts", "Inbox")

_ARGS = _parse_runtime_args()
_configure_talker_paths(_ARGS.talker_root)

def _ensure_talker_paths():
  os.makedirs(_TALKER_INBOX_ROOT, exist_ok=True)

def _ensure_talker_looper_started():
  """Start Talker looper via StartLoopsInWT.bat (safe to call repeatedly)."""
  global _TALKER_LOOPER_STARTED
  _ensure_talker_paths()
  if _TALKER_LOOPER_STARTED:
    return
  if not os.path.isfile(_START_LOOPS_BAT):
    raise RuntimeError(f"Looper launcher not found: {_START_LOOPS_BAT}")

  cmd = ["cmd", "/c", _START_LOOPS_BAT, _TALKER_ROOT]
  print(f"[BOOT] launching looper: {cmd!r}")
  proc = subprocess.run(
    cmd,
    cwd=_LOOPER_ROOT if os.path.isdir(_LOOPER_ROOT) else None,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    timeout=60,
    check=False,
  )
  if proc.returncode != 0:
    detail = (proc.stderr or proc.stdout or "").strip()
    raise RuntimeError(f"StartLoopsInWT failed (exit={proc.returncode}): {detail}")
  _TALKER_LOOPER_STARTED = True

# --- Console output mode: "quiet" (default) or "full" ---
_CONSOLE_MODE = "full"
# Stream visibility controls for Telegram output
_SHOW_REASONING = False
_SHOW_COMMANDS = False

# Ensure directory exists and load initial state
_ensure_session_dir()
_CURRENT_SESSION_DIR = _get_latest_session_dir()
if _CURRENT_SESSION_DIR is None:
  _create_new_session_dir()

# --- File delivery settings ---
_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB Telegram limit

# --- Async submit + delivery runtime ---
_BOOT_LOCK = asyncio.Lock()
_SUBMIT_LOCK = asyncio.Lock()
_DELIVERY_SEND_LOCK = asyncio.Lock()
_DELIVERY_TASK: Optional[asyncio.Task] = None
_DELIVERY_STOP_EVENT: Optional[asyncio.Event] = None
_DELIVERY_STATE_PATH = os.path.join(os.getcwd(), "gateway_delivery_state.json")
_DELIVERY_STATE_VERSION = 2
_DELIVERY_STATE: Dict[str, Any] = {}
_DELIVERY_STATE_LOADED = False
_DELIVERY_STATE_WAS_FRESH = False
_DELIVERY_STATE_LOCK = threading.Lock()
_DELIVERY_MAX_EVENT_KEYS_PER_RESULT = 4000

def _is_allowed(update: Update) -> bool:
  chat = update.effective_chat
  return bool(chat) and chat.id == ALLOWED_CHAT_ID_INT

def _clip(s: str, limit: int = 3500) -> str:
  # Telegram message limit is ~4096 chars; keep margin.
  if len(s) <= limit:
    return s
  return s[:limit] + "\n...(truncated)"

def _parse_on_off_arg(args: List[str], *, command_name: str) -> Tuple[Optional[bool], Optional[str]]:
  """
  Parse optional switch argument for commands like /show_reasoning and /show_commands.
  Returns (value, error). value is None when no args provided.
  """
  raw = " ".join(args).strip().lower()
  if not raw:
    return None, None
  if raw in ("on", "1", "true", "yes"):
    return True, None
  if raw in ("off", "0", "false", "no"):
    return False, None
  return None, f"Usage: /{command_name} on|off"

def _echo_console(update: Update):
  chat = update.effective_chat
  user = update.effective_user
  chat_id = chat.id if chat else None
  username = (user.username if user else None) or ""
  name = (user.full_name if user else None) or ""
  text = update.message.text if update.message else ""
  print(f"[TG] chat_id={chat_id} user={name} @{username} text={text!r}")

def _append_raw(path: Optional[str], text: str):
  if not path or not text:
    return
  try:
    with open(path, "a", encoding="utf-8", errors="replace") as f:
      f.write(text)
  except Exception:
    pass

def _sanitize_sender_id(value: str) -> str:
  s = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
  s = s.strip("._-")
  if not s:
    return "tg_unknown"
  return s[:80]

def _resolve_sender_id(update: Update) -> str:
  if _SENDER_ID_OVERRIDE:
    return _sanitize_sender_id(_SENDER_ID_OVERRIDE)
  user = update.effective_user
  if user and user.username:
    return _sanitize_sender_id(f"tg_{user.username}")
  if user:
    return _sanitize_sender_id(f"tg_{user.id}")
  return "tg_unknown"

def _sanitize_file_name(value: str) -> str:
  name = (value or "").strip()
  if not name:
    return "file.bin"
  name = os.path.basename(name.replace("\\", "/"))
  name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
  name = name.strip("._")
  if not name:
    return "file.bin"
  return name[:180]

def _sender_files_dir(sender_id: str) -> str:
  return os.path.join(_TALKER_INBOX_ROOT, sender_id, "Files")

def _allocate_incoming_file_path(sender_id: str, original_name: str) -> str:
  files_dir = _sender_files_dir(sender_id)
  os.makedirs(files_dir, exist_ok=True)
  safe_name = _sanitize_file_name(original_name)
  stamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S_%f")[:-3]
  candidate = os.path.join(files_dir, f"{stamp}_{safe_name}")
  if not os.path.exists(candidate):
    return candidate
  base, ext = os.path.splitext(safe_name)
  for i in range(1, 1000):
    candidate = os.path.join(files_dir, f"{stamp}_{base}_{i:03d}{ext}")
    if not os.path.exists(candidate):
      return candidate
  raise RuntimeError(f"Could not allocate incoming file name in {files_dir}")

def _make_prompt_marker() -> str:
  now = datetime.now()
  millis = int(now.microsecond / 1000)
  return now.strftime("%Y_%m_%d_%H_%M_%S_") + f"{millis:03d}"

def _allocate_prompt_paths(sender_dir: str) -> Tuple[str, str, str]:
  """Returns (marker, prompt_path, result_path), ensuring no collisions."""
  os.makedirs(sender_dir, exist_ok=True)
  base = _make_prompt_marker()
  for attempt in range(0, 1000):
    marker = base if attempt == 0 else f"{base}_t{attempt:03d}"
    if _PROMPT_TIMESTAMP_RE.fullmatch(marker) is None:
      continue
    prompt_path = os.path.join(sender_dir, f"Prompt_{marker}.md")
    result_path = os.path.join(sender_dir, f"Prompt_{marker}_Result.md")
    if not os.path.exists(prompt_path) and not os.path.exists(result_path):
      return marker, prompt_path, result_path
  raise RuntimeError(f"Could not allocate unique prompt marker in {sender_dir}")

def _write_prompt_atomic(prompt_path: str, text: str):
  parent = os.path.dirname(prompt_path)
  os.makedirs(parent, exist_ok=True)
  tmp_name = f".tmp_{uuid.uuid4().hex}.part"
  tmp_path = os.path.join(parent, tmp_name)
  try:
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
      f.write(text)
      if not text.endswith("\n"):
        f.write("\n")
    os.replace(tmp_path, prompt_path)
  finally:
    try:
      if os.path.exists(tmp_path):
        os.remove(tmp_path)
    except Exception:
      pass

def _resolve_codex_path() -> str:
  # Try to find codex in PATH, fallback to known npm location (Windows).
  codex_path = shutil.which("codex") or shutil.which("codex.cmd")
  if codex_path:
    return codex_path
  npm_path = os.path.expandvars(r"%APPDATA%\npm\codex.cmd")
  if os.path.exists(npm_path):
    return npm_path
  return "codex"  # Let it fail with FileNotFoundError

def _delivery_now_str() -> str:
  return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _parse_prompt_sort_key(marker: str) -> Optional[Tuple[int, int, int, int, int, int, int, str]]:
  match = _PROMPT_TIMESTAMP_RE.fullmatch((marker or "").strip())
  if not match:
    return None
  year = int(match.group("year"))
  month = int(match.group("month"))
  day = int(match.group("day"))
  hour = int(match.group("hour"))
  minute = int(match.group("minute"))
  second = int(match.group("second"))
  millis = int(match.group("millis"))
  suffix = match.group("suffix") or ""
  try:
    datetime(year, month, day, hour, minute, second, millis * 1000)
  except ValueError:
    return None
  return year, month, day, hour, minute, second, millis, suffix

def _extract_result_marker(file_name: str) -> Optional[str]:
  if not (file_name.startswith("Prompt_") and file_name.endswith("_Result.md")):
    return None
  marker = file_name[len("Prompt_"):-len("_Result.md")]
  if _parse_prompt_sort_key(marker) is None:
    return None
  return marker

def _new_delivery_state() -> Dict[str, Any]:
  return {
    "version": _DELIVERY_STATE_VERSION,
    "epoch": 0,
    "global_min_marker": "",
    "sender_min_marker": {},
    "sender_chat_ids": {},
    "result_offsets": {},
    "updated_at": _delivery_now_str(),
  }

def _load_delivery_state():
  global _DELIVERY_STATE, _DELIVERY_STATE_LOADED, _DELIVERY_STATE_WAS_FRESH
  if _DELIVERY_STATE_LOADED:
    return
  fresh = False
  state = _new_delivery_state()
  if os.path.isfile(_DELIVERY_STATE_PATH):
    try:
      with open(_DELIVERY_STATE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
      if isinstance(raw, dict):
        try:
          state["epoch"] = max(0, int(raw.get("epoch", 0)))
        except Exception:
          state["epoch"] = 0
        state["global_min_marker"] = str(raw.get("global_min_marker") or "")
        state["sender_min_marker"] = dict(raw.get("sender_min_marker") or {})
        state["sender_chat_ids"] = dict(raw.get("sender_chat_ids") or {})
        state["result_offsets"] = dict(raw.get("result_offsets") or {})
        state["updated_at"] = str(raw.get("updated_at") or _delivery_now_str())
    except Exception as e:
      print(f"[WARN] Failed to read delivery state, starting fresh: {e}")
      fresh = True
  else:
    fresh = True

  _DELIVERY_STATE = state
  _DELIVERY_STATE_LOADED = True
  _DELIVERY_STATE_WAS_FRESH = fresh

def _save_delivery_state() -> bool:
  if not _DELIVERY_STATE_LOADED:
    return True
  last_error = None
  for attempt in range(0, 3):
    try:
      payload = {
        "version": _DELIVERY_STATE_VERSION,
        "epoch": int(_DELIVERY_STATE.get("epoch", 0)),
        "global_min_marker": str(_DELIVERY_STATE.get("global_min_marker") or ""),
        "sender_min_marker": _DELIVERY_STATE.get("sender_min_marker", {}),
        "sender_chat_ids": _DELIVERY_STATE.get("sender_chat_ids", {}),
        "result_offsets": _DELIVERY_STATE.get("result_offsets", {}),
        "updated_at": _delivery_now_str(),
      }
      tmp_path = _DELIVERY_STATE_PATH + ".tmp"
      with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
      os.replace(tmp_path, _DELIVERY_STATE_PATH)
      return True
    except Exception as e:
      last_error = e
      if attempt < 2:
        time.sleep(0.05)
  print(f"[WARN] Failed to save delivery state: {last_error}")
  return False

def _result_state_key(sender_id: str, result_name: str) -> str:
  return f"{sender_id}/{result_name}"

def _get_result_entry(sender_id: str, result_name: str) -> Dict[str, Any]:
  offsets = _DELIVERY_STATE.setdefault("result_offsets", {})
  key = _result_state_key(sender_id, result_name)
  raw = offsets.get(key)
  if not isinstance(raw, dict):
    raw = {}
  raw.setdefault("offset", 0)
  raw.setdefault("completed", False)
  raw.setdefault("delivered_event_keys", [])
  raw.setdefault("updated_at", _delivery_now_str())
  offsets[key] = raw
  return raw

def _get_result_offset(sender_id: str, result_name: str) -> int:
  raw = _get_result_entry(sender_id, result_name)
  try:
    return max(0, int(raw.get("offset", 0)))
  except Exception:
    return 0

def _get_result_completed(sender_id: str, result_name: str) -> bool:
  raw = _get_result_entry(sender_id, result_name)
  return bool(raw.get("completed", False))

def _get_result_delivered_event_keys(sender_id: str, result_name: str) -> Set[str]:
  raw = _get_result_entry(sender_id, result_name)
  values = raw.get("delivered_event_keys")
  if not isinstance(values, list):
    return set()
  result: Set[str] = set()
  for value in values:
    if not value:
      continue
    result.add(str(value))
  return result

def _append_result_delivered_event_key(sender_id: str, result_name: str, event_key: str):
  raw = _get_result_entry(sender_id, result_name)
  values = raw.get("delivered_event_keys")
  if not isinstance(values, list):
    values = []
  values = [str(v) for v in values if v]
  if event_key in values:
    raw["delivered_event_keys"] = values
    return
  values.append(event_key)
  if len(values) > _DELIVERY_MAX_EVENT_KEYS_PER_RESULT:
    values = values[-_DELIVERY_MAX_EVENT_KEYS_PER_RESULT:]
  raw["delivered_event_keys"] = values

def _set_result_state(sender_id: str, result_name: str, offset: int, completed: bool,
                      delivered_event_keys: Optional[Any] = None):
  entry = {
    "offset": int(max(0, offset)),
    "completed": bool(completed),
    "delivered_event_keys": [],
    "updated_at": _delivery_now_str(),
  }
  if delivered_event_keys:
    if isinstance(delivered_event_keys, list):
      ordered = [str(v) for v in delivered_event_keys if v]
    else:
      ordered = [str(v) for v in delivered_event_keys if v]
    if len(ordered) > _DELIVERY_MAX_EVENT_KEYS_PER_RESULT:
      ordered = ordered[-_DELIVERY_MAX_EVENT_KEYS_PER_RESULT:]
    entry["delivered_event_keys"] = ordered
  offsets = _DELIVERY_STATE.setdefault("result_offsets", {})
  key = _result_state_key(sender_id, result_name)
  offsets[key] = entry

def _get_state_epoch() -> int:
  try:
    return int(_DELIVERY_STATE.get("epoch", 0))
  except Exception:
    return 0

def _bump_state_epoch() -> int:
  epoch = _get_state_epoch() + 1
  _DELIVERY_STATE["epoch"] = epoch
  return epoch

def _set_sender_chat(sender_id: str, chat_id: int):
  mapping = _DELIVERY_STATE.setdefault("sender_chat_ids", {})
  mapping[sender_id] = int(chat_id)

def _get_sender_chat(sender_id: str) -> Optional[int]:
  mapping = _DELIVERY_STATE.get("sender_chat_ids", {})
  raw = mapping.get(sender_id)
  if raw is None:
    return None
  try:
    return int(raw)
  except Exception:
    return None

def _forget_sender_delivery_state(sender_id: str):
  mapping = _DELIVERY_STATE.get("sender_chat_ids", {})
  if isinstance(mapping, dict):
    mapping.pop(sender_id, None)
  offsets = _DELIVERY_STATE.get("result_offsets", {})
  if isinstance(offsets, dict):
    to_delete = [k for k in offsets.keys() if k.startswith(f"{sender_id}/")]
    for key in to_delete:
      offsets.pop(key, None)

def _forget_all_delivery_state():
  _DELIVERY_STATE["global_min_marker"] = ""
  _DELIVERY_STATE["sender_min_marker"] = {}
  _DELIVERY_STATE["sender_chat_ids"] = {}
  _DELIVERY_STATE["result_offsets"] = {}

def _set_sender_min_marker(sender_id: str, marker: str):
  markers = _DELIVERY_STATE.setdefault("sender_min_marker", {})
  markers[sender_id] = marker

def _set_global_min_marker(marker: str):
  _DELIVERY_STATE["global_min_marker"] = marker

def _marker_is_older(marker: str, min_marker: str) -> bool:
  if not min_marker:
    return False
  marker_key = _parse_prompt_sort_key(marker)
  floor_key = _parse_prompt_sort_key(min_marker)
  if marker_key is None or floor_key is None:
    return False
  return marker_key < floor_key

def _is_marker_blocked_by_reset(sender_id: str, marker: str) -> bool:
  global_floor = str(_DELIVERY_STATE.get("global_min_marker") or "")
  sender_floor = str((_DELIVERY_STATE.get("sender_min_marker") or {}).get(sender_id) or "")
  return _marker_is_older(marker, global_floor) or _marker_is_older(marker, sender_floor)

def _bootstrap_delivery_state_to_tail():
  """
  On first run of async delivery, avoid replaying historical results by tailing
  currently existing files.
  """
  if not _DELIVERY_STATE_WAS_FRESH:
    return
  candidates = _list_result_candidates()
  with _DELIVERY_STATE_LOCK:
    for _, sender_id, result_name, result_path in candidates:
      key = _result_state_key(sender_id, result_name)
      offsets = _DELIVERY_STATE.setdefault("result_offsets", {})
      if key in offsets:
        continue
      try:
        size = os.path.getsize(result_path)
      except Exception:
        size = 0
      _set_result_state(sender_id, result_name, size, completed=True)
    _save_delivery_state()

def _list_result_candidates() -> List[Tuple[Tuple[int, int, int, int, int, int, int, str], str, str, str]]:
  """
  Returns sorted list of result files:
  (marker_sort_key, sender_id, file_name, absolute_path)
  """
  candidates: List[Tuple[Tuple[int, int, int, int, int, int, int, str], str, str, str]] = []
  if not os.path.isdir(_TALKER_INBOX_ROOT):
    return candidates

  for sender_id in sorted(os.listdir(_TALKER_INBOX_ROOT)):
    sender_dir = os.path.join(_TALKER_INBOX_ROOT, sender_id)
    if not os.path.isdir(sender_dir):
      continue
    try:
      names = os.listdir(sender_dir)
    except Exception:
      continue
    for file_name in names:
      marker = _extract_result_marker(file_name)
      if not marker:
        continue
      sort_key = _parse_prompt_sort_key(marker)
      if sort_key is None:
        continue
      full_path = os.path.join(sender_dir, file_name)
      if not os.path.isfile(full_path):
        continue
      candidates.append((sort_key, sender_id, file_name, full_path))

  candidates.sort(key=lambda item: (item[0], item[1], item[2].lower()))
  return candidates

def _make_delivery_event_key(kind: str, line_offset: int, item_index: int, payload: str) -> str:
  h = hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:16]
  return f"{kind}:{line_offset}:{item_index}:{h}"

def _state_snapshot(sender_id: str, result_name: str, marker: str) -> Tuple[int, bool, int, Set[str], Optional[int], bool]:
  with _DELIVERY_STATE_LOCK:
    offset = _get_result_offset(sender_id, result_name)
    completed = _get_result_completed(sender_id, result_name)
    epoch = _get_state_epoch()
    delivered = _get_result_delivered_event_keys(sender_id, result_name)
    chat_id = _get_sender_chat(sender_id)
    blocked = _is_marker_blocked_by_reset(sender_id, marker)
    return offset, completed, epoch, delivered, chat_id, blocked

def _state_commit_result(sender_id: str, result_name: str, offset: int, completed: bool,
                         expected_epoch: int) -> bool:
  with _DELIVERY_STATE_LOCK:
    if _get_state_epoch() != expected_epoch:
      return False
    raw = _get_result_entry(sender_id, result_name)
    keys = raw.get("delivered_event_keys")
    if not isinstance(keys, list):
      keys = []
    _set_result_state(sender_id, result_name, offset, completed, keys)
    return _save_delivery_state()

def _state_mark_event_delivered(sender_id: str, result_name: str, event_key: str,
                                expected_epoch: int) -> bool:
  with _DELIVERY_STATE_LOCK:
    if _get_state_epoch() != expected_epoch:
      return False
    delivered = _get_result_delivered_event_keys(sender_id, result_name)
    if event_key in delivered:
      return True
    _append_result_delivered_event_key(sender_id, result_name, event_key)
    return _save_delivery_state()

def _state_epoch_matches(expected_epoch: int) -> bool:
  with _DELIVERY_STATE_LOCK:
    return _get_state_epoch() == expected_epoch

async def _ensure_talker_looper_started_async():
  if _SKIP_TALKER_BOOT:
    return
  async with _BOOT_LOCK:
    if _TALKER_LOOPER_STARTED:
      return
    await asyncio.to_thread(_ensure_talker_looper_started)

_load_delivery_state()
if _SENDER_ID_OVERRIDE:
  with _DELIVERY_STATE_LOCK:
    _set_sender_chat(_sanitize_sender_id(_SENDER_ID_OVERRIDE), ALLOWED_CHAT_ID_INT)
    _save_delivery_state()

# --- Runner-aware result parsing ---
_RUNNER_CACHE: Dict[str, str] = {}  # result_path -> runner_name

def _detect_runner_from_result(result_path: str) -> str:
  """Detect runner type from first line of result file (<!-- runner: X -->)."""
  if result_path in _RUNNER_CACHE:
    return _RUNNER_CACHE[result_path]
  
  try:
    with open(result_path, "r", encoding="utf-8") as f:
      first_line = f.readline()
  except Exception:
    return "codex"  # default
  
  match = re.match(r"^<!--\s*runner:\s*(\w+)\s*-->", first_line.strip())
  runner = match.group(1) if match else "codex"
  _RUNNER_CACHE[result_path] = runner
  return runner

def _extract_messages_with_runner(lines: List[str], runner_name: str) -> List[str]:
  """Extract agent messages using appropriate runner's extract_agent_messages."""
  if runner_name == "kimi":
    runner = KimiRunner()
  else:
    runner = CodexRunner()
  
  try:
    return runner.extract_agent_messages(lines)
  except Exception:
    return []

def _process_looper_json_line(line: str, started_commands: Dict[str, bool]) -> Tuple[List[str], bool]:
  """
  Parse one JSON line from result stream.
  Returns (messages_to_emit, saw_turn_completed).
  DEPRECATED: Use _extract_messages_with_runner for new code.
  """
  try:
    obj = json.loads(line)
  except Exception:
    return [], False

  messages: List[str] = []
  saw_turn_completed = False
  obj_type = str(obj.get("type") or "")

  if obj_type == "turn.completed":
    saw_turn_completed = True

  if obj_type == "item.started" and obj.get("item", {}).get("type") == "command_execution":
    item = obj["item"]
    item_id = str(item.get("id") or "")
    cmd = str(item.get("command") or "")
    if item_id:
      started_commands[item_id] = True
    if _SHOW_COMMANDS:
      messages.append(f"[command] {cmd} (in_progress)")
    return messages, saw_turn_completed

  if obj_type == "item.completed" and obj.get("item"):
    item = obj["item"]
    item_type = item.get("type")

    if item_type == "reasoning" and item.get("text") and _SHOW_REASONING:
      messages.append(f"[reasoning] {item['text']}")
      return messages, saw_turn_completed

    if item_type == "agent_message" and item.get("text"):
      messages.append(str(item["text"]))
      return messages, saw_turn_completed

    if item_type == "command_execution":
      if not _SHOW_COMMANDS:
        return messages, saw_turn_completed

      item_id = str(item.get("id") or "")
      cmd = str(item.get("command") or "")
      status = str(item.get("status") or "")
      code = item.get("exit_code")
      started_before = bool(item_id and item_id in started_commands)

      if started_before:
        if status == "completed":
          messages.append(f"[command] (exit={code})")
        elif status == "failed":
          messages.append(f"[command] (failed, exit={code})")
        elif status:
          messages.append(f"[command] ({status})")
        else:
          messages.append("[command]")
      else:
        if status == "completed":
          messages.append(f"[command] {cmd} (exit={code})")
        elif status == "failed":
          messages.append(f"[command] {cmd} (failed, exit={code})")
        elif status:
          messages.append(f"[command] {cmd} ({status})")
        else:
          messages.append(f"[command] {cmd}")

      aggregated_output = item.get("aggregated_output")
      if aggregated_output:
        messages.append(f"[command-output] {aggregated_output}")
      return messages, saw_turn_completed

  return messages, saw_turn_completed

def _extract_deliver_files(text: str) -> Tuple[str, List[str]]:
  """
  Extract DELIVER_FILE: directives from text.
  Returns (clean_text, list_of_paths).
  Directive format: DELIVER_FILE: <path> (on its own line, case-sensitive).
  """
  if not text:
    return "", []
  
  paths = []
  clean_lines = []
  
  # Pattern: DELIVER_FILE: followed by optional whitespace, then capture the path
  pattern = re.compile(r'^DELIVER_FILE:\s*(.+)$')
  
  for line in text.splitlines():
    match = pattern.match(line.strip())
    if match:
      paths.append(match.group(1).strip())
    else:
      clean_lines.append(line)
  
  # Remove trailing empty lines from clean_text
  while clean_lines and clean_lines[-1].strip() == "":
    clean_lines.pop()
  
  clean_text = "\n".join(clean_lines)
  return clean_text, paths

def _build_file_event_prompt(media_kind: str, saved_path: str, original_name: str,
                             caption: str, sender_id: str) -> str:
  lines: List[str] = []
  lines.append("Системное событие от gateway: пользователь прислал вложение.")
  lines.append(f"Sender ID: {sender_id}")
  lines.append(f"Тип вложения: {media_kind}")
  lines.append(f"Сохраненный файл: {saved_path}")
  lines.append(f"Исходное имя: {original_name}")
  if (caption or "").strip():
    lines.append("")
    lines.append("Подпись пользователя к файлу:")
    lines.append(caption.strip())
  else:
    lines.append("")
    lines.append("Подписи нет.")
  lines.append("")
  lines.append(
    "Если в текущем диалоге пользователь ранее просил действие над присланным файлом, "
    "выполни его используя путь выше."
  )
  return "\n".join(lines)

def _append_run_log(event: str, **fields: Any):
  """Append one metadata-only line to session run.log."""
  if not _CURRENT_SESSION_DIR:
    return
  try:
    run_log_path = os.path.join(_CURRENT_SESSION_DIR, "run.log")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base = [ts, event]
    for key in sorted(fields.keys()):
      value = fields[key]
      base.append(f"{key}={value}")
    with open(run_log_path, "a", encoding="utf-8") as f:
      f.write(" ".join(base) + "\n")
  except Exception:
    pass

def _user_info(update: Update) -> Tuple[int, str]:
  user = update.effective_user
  chat_id = update.effective_chat.id if update.effective_chat else 0
  user_info = f"@{user.username}" if user and user.username else (user.full_name if user else "unknown")
  return chat_id, user_info

async def _send_text(bot, chat_id: int, text: str):
  await bot.send_message(chat_id=chat_id, text=_clip(text))

async def _emit_stream_messages(bot, chat_id: int, messages: List[str], *,
                                sender_id: str, result_name: str, line_offset: int,
                                delivered_event_keys: Set[str], expected_epoch: int) -> Tuple[bool, bool]:
  emitted = False
  for msg_idx, message in enumerate(messages):
    clean_text, file_paths = _extract_deliver_files(message)
    if clean_text:
      event_key = _make_delivery_event_key("msg", line_offset, msg_idx, clean_text)
      if event_key not in delivered_event_keys:
        async with _DELIVERY_SEND_LOCK:
          if not _state_epoch_matches(expected_epoch):
            return emitted, False
          await _send_text(bot, chat_id, clean_text)
          if not _state_mark_event_delivered(sender_id, result_name, event_key, expected_epoch):
            return emitted, False
          delivered_event_keys.add(event_key)
          emitted = True

    for file_idx, raw_path in enumerate(file_paths):
      event_key = _make_delivery_event_key("file", line_offset, msg_idx * 1000 + file_idx, raw_path)
      if event_key in delivered_event_keys:
        continue
      async with _DELIVERY_SEND_LOCK:
        if not _state_epoch_matches(expected_epoch):
          return emitted, False

        if os.path.isabs(raw_path):
          file_path = raw_path
        else:
          file_path = os.path.join(_TALKER_ROOT or os.getcwd(), raw_path)
        file_path = os.path.normpath(file_path)
        basename = os.path.basename(file_path)

        if not os.path.isfile(file_path):
          await _send_text(bot, chat_id, f"File not found: {raw_path}")
          emitted = True
          continue

        try:
          file_size = os.path.getsize(file_path)
        except Exception as e:
          await _send_text(bot, chat_id, f"Failed to check size: {raw_path} ({e})")
          emitted = True
          continue

        if file_size > _MAX_FILE_SIZE:
          await _send_text(bot, chat_id, f"File too large: {raw_path} ({file_size} bytes)")
          emitted = True
          continue

        try:
          with open(file_path, "rb") as f:
            await bot.send_document(chat_id=chat_id, document=f, filename=basename, read_timeout=600, write_timeout=600)
          await _send_text(bot, chat_id, f"Sent: {basename} ({file_size} bytes)")
          if not _state_mark_event_delivered(sender_id, result_name, event_key, expected_epoch):
            return emitted, False
          delivered_event_keys.add(event_key)
          emitted = True
        except Exception as e:
          await _send_text(bot, chat_id, f"Failed to send: {raw_path} ({e})")
          emitted = True
  return emitted, True

async def _process_result_line(bot, chat_id: int, line: str, started_commands: Dict[str, bool],
                               *, sender_id: str, result_name: str, line_offset: int,
                               delivered_event_keys: Set[str], expected_epoch: int) -> Tuple[bool, bool, bool, bool]:
  """
  Process one result file line.
  Returns (turn_completed, finished_line, emitted_anything, state_ok).
  """
  trim = (line or "").strip()
  if not trim:
    return False, False, False, True

  # Ignore markdown framing lines produced by looper result writer.
  if (trim.startswith("# Codex Result for ") or 
      trim.startswith("Started: ") or 
      trim.startswith("--- Fallback:") or
      trim.startswith("<!-- runner:")):
    return False, False, False, True

  if trim.startswith("{") and trim.endswith("}"):
    messages, turn_completed = _process_looper_json_line(trim, started_commands)
    emitted, state_ok = await _emit_stream_messages(
      bot,
      chat_id,
      messages,
      sender_id=sender_id,
      result_name=result_name,
      line_offset=line_offset,
      delivered_event_keys=delivered_event_keys,
      expected_epoch=expected_epoch,
    )
    if _CONSOLE_MODE == "full":
      for msg in messages:
        print(f"[stream] {msg}")
    return turn_completed, False, emitted, state_ok

  finished_line = trim.startswith("Finished:")
  if trim.startswith("Command failed with exit code:") and _CONSOLE_MODE == "full":
    print(f"[stream] [error] {trim}")
  return False, finished_line, False, True

async def _process_result_file_incremental(bot, sender_id: str, result_name: str, result_marker: str, result_path: str,
                                           session_stdout_path: Optional[str]) -> Tuple[bool, bool]:
  """
  Process new records from one Result.md.
  Returns (state_changed, emitted_any).
  """
  offset, completed, epoch, delivered_event_keys, chat_id, marker_blocked = _state_snapshot(
    sender_id, result_name, result_marker
  )
  state_changed = False
  emitted_any = False

  try:
    file_size = os.path.getsize(result_path)
  except Exception:
    return False, False

  if file_size < offset:
    # File was truncated/recreated; start from beginning.
    offset = 0
    completed = False
    state_changed = True

  if file_size <= offset:
    if state_changed:
      committed = _state_commit_result(sender_id, result_name, offset, completed, epoch)
      if not committed:
        return False, emitted_any
    return state_changed, False

  if marker_blocked:
    committed = _state_commit_result(sender_id, result_name, file_size, True, epoch)
    return committed, False

  if chat_id is None:
    return False, False

  # Detect runner type from file header
  runner_name = _detect_runner_from_result(result_path)

  try:
    with open(result_path, "rb") as f:
      f.seek(offset)
      chunk = f.read()
  except Exception:
    return state_changed, False

  if not chunk:
    return state_changed, False

  _append_raw(session_stdout_path, chunk.decode("utf-8", errors="replace"))
  
  # For Kimi runner, use extract_agent_messages() on all lines
  if runner_name == "kimi":
    try:
      with open(result_path, "r", encoding="utf-8") as f:
        all_lines = f.read().splitlines()
    except Exception:
      return state_changed, False
    
    messages = _extract_messages_with_runner(all_lines, runner_name)
    new_messages = []
    for msg in messages:
      msg_hash = hashlib.md5(msg.encode("utf-8")).hexdigest()[:16]
      event_key = f"msg:{msg_hash}"
      if event_key not in delivered_event_keys:
        new_messages.append((msg, event_key))
    
    for msg, event_key in new_messages:
      try:
        await _send_text(bot, chat_id, msg)
      except Exception:
        # Still commit offset to avoid infinite loop
        offset = file_size
        _state_commit_result(sender_id, result_name, offset, completed, epoch)
        return False, emitted_any
      
      mark_result = _state_mark_event_delivered(sender_id, result_name, event_key, epoch)
      if not mark_result:
        # Still commit offset to avoid infinite loop
        offset = file_size
        _state_commit_result(sender_id, result_name, offset, completed, epoch)
        return False, emitted_any
      delivered_event_keys.add(event_key)
      emitted_any = True
      if _CONSOLE_MODE == "full":
        print(f"[stream] {msg}")
    
    # Check for completion markers
    chunk_text = chunk.decode("utf-8", errors="replace")
    if "Finished:" in chunk_text:
      completed = True
    
    offset = file_size  # Kimi output is processed as a whole
    committed = _state_commit_result(sender_id, result_name, offset, completed, epoch)
    if not committed:
      return False, emitted_any
    return True, emitted_any

  # Codex runner: process line by line (original logic)
  started_commands: Dict[str, bool] = {}
  consumed = 0

  while True:
    line_start_offset = offset + consumed
    nl = chunk.find(b"\n", consumed)
    if nl < 0:
      break
    line_bytes = chunk[consumed:nl]
    consumed = nl + 1
    line = line_bytes.decode("utf-8", errors="replace").rstrip("\r")
    turn_completed, finished_line, emitted, state_ok = await _process_result_line(
      bot,
      chat_id,
      line,
      started_commands,
      sender_id=sender_id,
      result_name=result_name,
      line_offset=line_start_offset,
      delivered_event_keys=delivered_event_keys,
      expected_epoch=epoch,
    )
    if not state_ok:
      return False, emitted_any
    completed = completed or turn_completed or finished_line
    emitted_any = emitted_any or emitted
    if line.strip().startswith("Command failed with exit code:"):
      completed = True

  # Support complete records without trailing newline.
  if consumed < len(chunk):
    tail = chunk[consumed:]
    tail_text = tail.decode("utf-8", errors="replace").strip()
    tail_complete = False
    if tail_text.startswith("{") and tail_text.endswith("}"):
      try:
        json.loads(tail_text)
        tail_complete = True
      except Exception:
        tail_complete = False
    elif tail_text.startswith("Finished:") or tail_text.startswith("Command failed with exit code:"):
      tail_complete = True

    if tail_complete:
      line_start_offset = offset + consumed
      turn_completed, finished_line, emitted, state_ok = await _process_result_line(
        bot,
        chat_id,
        tail_text,
        started_commands,
        sender_id=sender_id,
        result_name=result_name,
        line_offset=line_start_offset,
        delivered_event_keys=delivered_event_keys,
        expected_epoch=epoch,
      )
      if not state_ok:
        return False, emitted_any
      consumed = len(chunk)
      completed = completed or turn_completed or finished_line
      emitted_any = emitted_any or emitted
      if tail_text.startswith("Command failed with exit code:"):
        completed = True

  if consumed <= 0 and not state_changed:
    return False, emitted_any

  offset += consumed
  committed = _state_commit_result(sender_id, result_name, offset, completed, epoch)
  if not committed:
    return False, emitted_any
  _append_run_log(
    "DELIVER",
    sender=sender_id,
    result=result_name,
    offset=offset,
    completed=completed,
    emitted=emitted_any,
  )
  return True, emitted_any

async def _delivery_worker_loop(application: Application):
  global _DELIVERY_STOP_EVENT
  if _DELIVERY_STOP_EVENT is None:
    _DELIVERY_STOP_EVENT = asyncio.Event()

  session_stdout_path, session_stderr_path = _get_session_log_paths()
  if not session_stdout_path or not session_stderr_path:
    _ensure_temp_dir()
    session_stdout_path = os.path.join(_TEMP_DIR, "_temp_stdout.log")
    session_stderr_path = os.path.join(_TEMP_DIR, "_temp_stderr.log")

  print("[DELIVER] worker started")
  while not _DELIVERY_STOP_EVENT.is_set():
    changed_any = False
    emitted_any = False
    try:
      for _, sender_id, result_name, result_path in _list_result_candidates():
        marker = _extract_result_marker(result_name) or ""
        changed, emitted = await _process_result_file_incremental(
          application.bot,
          sender_id,
          result_name,
          marker,
          result_path,
          session_stdout_path,
        )
        changed_any = changed_any or changed
        emitted_any = emitted_any or emitted
    except Exception as e:
      _append_raw(session_stderr_path, f"[ERROR] delivery worker loop: {e}\n")
      _append_run_log("DELIVER_ERROR", error=repr(e))

    wait_for = _RESULT_POLL_ACTIVE_SEC if (changed_any or emitted_any) else _RESULT_POLL_IDLE_SEC
    try:
      await asyncio.wait_for(_DELIVERY_STOP_EVENT.wait(), timeout=max(0.05, wait_for))
    except asyncio.TimeoutError:
      continue
  print("[DELIVER] worker stopped")

async def _start_delivery_worker(application: Application):
  global _DELIVERY_TASK, _DELIVERY_STOP_EVENT
  if _DELIVERY_TASK and not _DELIVERY_TASK.done():
    return
  _DELIVERY_STOP_EVENT = asyncio.Event()
  # Use raw asyncio task management: this worker is started during post_init and
  # stopped explicitly in post_shutdown.
  _DELIVERY_TASK = asyncio.create_task(_delivery_worker_loop(application))

async def _stop_delivery_worker():
  global _DELIVERY_TASK, _DELIVERY_STOP_EVENT
  if _DELIVERY_STOP_EVENT is not None:
    _DELIVERY_STOP_EVENT.set()
  if _DELIVERY_TASK is not None:
    _DELIVERY_TASK.cancel()
    try:
      await _DELIVERY_TASK
    except asyncio.CancelledError:
      pass
  _DELIVERY_TASK = None
  _DELIVERY_STOP_EVENT = None

def _validate_reset_scope():
  """
  Safety guard: reset operations are allowed only inside TALKER_ROOT/Prompts/Inbox.
  """
  inbox_abs = os.path.abspath(_TALKER_INBOX_ROOT)
  talker_abs = os.path.abspath(_TALKER_ROOT)
  try:
    common = os.path.commonpath([inbox_abs, talker_abs])
  except ValueError:
    raise RuntimeError(f"Unsafe reset scope (different drives): inbox={inbox_abs} talker={talker_abs}")
  if os.path.normcase(common) != os.path.normcase(talker_abs):
    raise RuntimeError(f"Unsafe reset scope (inbox outside talker root): {inbox_abs}")

  rel = os.path.relpath(inbox_abs, talker_abs)
  parts = [p for p in rel.split(os.sep) if p not in ("", ".")]
  if len(parts) != 2 or os.path.normcase(parts[0]) != "prompts" or os.path.normcase(parts[1]) != "inbox":
    raise RuntimeError(f"Unsafe reset scope (expected Talker/Prompts/Inbox): {inbox_abs}")

def _is_prompt_artifact_name(name: str) -> bool:
  """
  Strictly match Looper prompt/result markdown files:
    Prompt_<timestamp>[ _suffix].md
    Prompt_<timestamp>[ _suffix]_Result.md
  """
  if not (name.startswith("Prompt_") and name.endswith(".md")):
    return False

  body = name[len("Prompt_"):-len(".md")]
  if body.endswith("_Result"):
    marker = body[:-len("_Result")]
  else:
    marker = body
  return _PROMPT_TIMESTAMP_RE.fullmatch(marker) is not None

def _ensure_sender_dir_in_scope(sender_dir: str):
  """
  Safety guard: sender_dir must stay inside inbox even after resolving links.
  """
  inbox_abs = os.path.abspath(_TALKER_INBOX_ROOT)
  sender_abs = os.path.abspath(sender_dir)
  try:
    common_abs = os.path.commonpath([sender_abs, inbox_abs])
  except ValueError:
    raise RuntimeError(f"Unsafe sender dir (different drives): {sender_abs}")
  if os.path.normcase(common_abs) != os.path.normcase(inbox_abs):
    raise RuntimeError(f"Unsafe sender dir (outside inbox): {sender_abs}")

  inbox_real = os.path.realpath(_TALKER_INBOX_ROOT)
  sender_real = os.path.realpath(sender_dir)
  try:
    common_real = os.path.commonpath([sender_real, inbox_real])
  except ValueError:
    raise RuntimeError(f"Unsafe sender dir (different realpath drives): {sender_real}")
  if os.path.normcase(common_real) != os.path.normcase(inbox_real):
    raise RuntimeError(f"Unsafe sender dir (resolved outside inbox): {sender_real}")

def _clear_sender_artifacts(sender_dir: str) -> int:
  """
  Remove only known queue/session artifacts. Keep directories and unrelated files.
  """
  _ensure_sender_dir_in_scope(sender_dir)
  removed = 0
  try:
    names = os.listdir(sender_dir)
  except Exception:
    return 0

  for name in names:
    should_remove = False
    if name == "loop_state.json":
      should_remove = True
    elif re.fullmatch(r"loop_state\.corrupt\..+\.json", name):
      should_remove = True
    elif name.startswith(".tmp_") and name.endswith(".part"):
      should_remove = True
    elif name.endswith(".tmp"):
      should_remove = True
    elif _is_prompt_artifact_name(name):
      should_remove = True

    if not should_remove:
      continue

    path = os.path.join(sender_dir, name)
    if not os.path.isfile(path):
      continue
    try:
      os.remove(path)
      removed += 1
    except Exception:
      pass
  return removed

def _reset_sender_dir(sender_id: str) -> int:
  _validate_reset_scope()
  sender_dir = os.path.join(_TALKER_INBOX_ROOT, sender_id)
  os.makedirs(sender_dir, exist_ok=True)
  with _DELIVERY_STATE_LOCK:
    _bump_state_epoch()
    _set_sender_min_marker(sender_id, _make_prompt_marker())
    _forget_sender_delivery_state(sender_id)
    if not _save_delivery_state():
      raise RuntimeError("Failed to persist delivery state during reset_session")
  removed = _clear_sender_artifacts(sender_dir)
  return removed

def _create_reset_signal() -> bool:
  """Create reset signal for Looper to clear in-memory state."""
  try:
    signal_path = os.path.join(_TALKER_INBOX_ROOT, "reset_signal.json")
    with open(signal_path, "w", encoding="utf-8") as f:
      json.dump({"timestamp": _delivery_now_str(), "action": "reset_signal"}, f)
    return True
  except Exception:
    return False

def _reset_all_sender_dirs() -> Tuple[int, int]:
  _validate_reset_scope()
  _ensure_talker_paths()
  with _DELIVERY_STATE_LOCK:
    _bump_state_epoch()
    _forget_all_delivery_state()
    _set_global_min_marker(_make_prompt_marker())
    if not _save_delivery_state():
      raise RuntimeError("Failed to persist delivery state during reset_all")
  sender_count = 0
  removed_files = 0
  for name in os.listdir(_TALKER_INBOX_ROOT):
    path = os.path.join(_TALKER_INBOX_ROOT, name)
    if not os.path.isdir(path):
      continue
    sender_count += 1
    try:
      removed = _clear_sender_artifacts(path)
      removed_files += removed
    except Exception:
      pass
  return sender_count, removed_files

async def _submit_prompt(update: Update, prompt: str, source: str) -> Optional[str]:
  global _CURRENT_SESSION_DIR

  prompt = (prompt or "").strip()
  if not prompt:
    await update.message.reply_text("Empty prompt.")
    return None

  if _CURRENT_SESSION_DIR is None:
    _create_new_session_dir()

  chat_id, user_info = _user_info(update)
  sender_id = _resolve_sender_id(update)
  started_at = time.monotonic()
  marker = ""
  status = "ok"
  error_text = ""

  _append_run_log(
    "SUBMIT_START",
    chat_id=chat_id,
    user=user_info,
    sender=sender_id,
    source=source,
    prompt_len=len(prompt),
    session=os.path.basename(_CURRENT_SESSION_DIR or "none"),
  )

  try:
    await _ensure_talker_looper_started_async()
    async with _SUBMIT_LOCK:
      sender_dir = os.path.join(_TALKER_INBOX_ROOT, sender_id)
      marker, prompt_path, result_path = _allocate_prompt_paths(sender_dir)
      result_name = os.path.basename(result_path)
      with _DELIVERY_STATE_LOCK:
        _set_sender_chat(sender_id, chat_id)
        _set_result_state(sender_id, result_name, 0, completed=False)
        if not _save_delivery_state():
          raise RuntimeError("Failed to persist delivery state before submit")

      try:
        _write_prompt_atomic(prompt_path, prompt)
      except Exception:
        # Prompt creation failed after state write: remove orphan state entry.
        with _DELIVERY_STATE_LOCK:
          offsets = _DELIVERY_STATE.get("result_offsets", {})
          if isinstance(offsets, dict):
            offsets.pop(_result_state_key(sender_id, result_name), None)
          _save_delivery_state()
        raise

    session_stdout_path, session_stderr_path = _get_session_log_paths()
    if not session_stdout_path or not session_stderr_path:
      _ensure_temp_dir()
      session_stdout_path = os.path.join(_TEMP_DIR, "_temp_stdout.log")
      session_stderr_path = os.path.join(_TEMP_DIR, "_temp_stderr.log")

    _append_raw(session_stdout_path, f"\n=== SUBMIT marker={marker} sender={sender_id} source={source} ===\n")
    _append_raw(session_stdout_path, f"Prompt file: {prompt_path}\n")
    _append_raw(session_stdout_path, f"Result file: {result_path}\n")
    return marker
  except Exception as e:
    status = "error"
    error_text = str(e)
    try:
      await update.message.reply_text(f"Submit failed: {e}")
    except Exception:
      pass
    return None
  finally:
    duration_ms = int((time.monotonic() - started_at) * 1000)
    _append_run_log(
      "SUBMIT_END",
      chat_id=chat_id,
      user=user_info,
      sender=sender_id,
      source=source,
      marker=marker or "-",
      status=status,
      duration_ms=duration_ms,
      error=repr(error_text) if error_text else "-",
    )

async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)

  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  msg = update.message
  if not msg:
    return

  tg_media = None
  original_name = ""
  media_kind = "file"

  if msg.document:
    tg_media = msg.document
    original_name = msg.document.file_name or f"document_{msg.document.file_unique_id}.bin"
    media_kind = "document"
  elif msg.audio:
    tg_media = msg.audio
    original_name = msg.audio.file_name or f"audio_{msg.audio.file_unique_id}.mp3"
    media_kind = "audio"
  elif msg.video:
    tg_media = msg.video
    original_name = msg.video.file_name or f"video_{msg.video.file_unique_id}.mp4"
    media_kind = "video"
  elif msg.voice:
    tg_media = msg.voice
    original_name = f"voice_{msg.voice.file_unique_id}.ogg"
    media_kind = "voice"
  elif msg.photo:
    tg_media = msg.photo[-1]
    original_name = f"photo_{tg_media.file_unique_id}.jpg"
    media_kind = "photo"
  elif msg.video_note:
    tg_media = msg.video_note
    original_name = f"video_note_{msg.video_note.file_unique_id}.mp4"
    media_kind = "video_note"

  if tg_media is None:
    await update.message.reply_text("Unsupported attachment type.")
    return

  sender_id = _resolve_sender_id(update)
  final_path = _allocate_incoming_file_path(sender_id, original_name)
  tmp_path = final_path + ".part"
  caption = (msg.caption or "").strip()

  try:
    tg_file = await tg_media.get_file()
    await tg_file.download_to_drive(custom_path=tmp_path)
    os.replace(tmp_path, final_path)
    size = os.path.getsize(final_path)
    await update.message.reply_text(
      f"Saved {media_kind}: {os.path.basename(final_path)} ({size} bytes)\n"
      f"Path: {final_path}"
    )
    auto_prompt = _build_file_event_prompt(
      media_kind=media_kind,
      saved_path=final_path,
      original_name=original_name,
      caption=caption,
      sender_id=sender_id,
    )
    await _submit_prompt(update, auto_prompt, source=f"file:{media_kind}")
  except Exception as e:
    await update.message.reply_text(f"Failed to save attachment: {e}")
  finally:
    try:
      if os.path.exists(tmp_path):
        os.remove(tmp_path)
    except Exception:
      pass

# --- Telegram handlers ---

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  chat = update.effective_chat
  if not chat:
    return
  await update.message.reply_text(f"chat_id = {chat.id}")

async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  sender_id = _resolve_sender_id(update)
  worker_alive = bool(_DELIVERY_TASK and not _DELIVERY_TASK.done())
  with _DELIVERY_STATE_LOCK:
    delivery_epoch = _get_state_epoch()
  await update.message.reply_text(
    f"current_agent = {_CURRENT_AGENT}\n"
    f"looper_root = {_LOOPER_ROOT}\n"
    f"talker_root = {_TALKER_ROOT}\n"
    f"inbox_root = {_TALKER_INBOX_ROOT}\n"
    f"sender_id = {sender_id}\n"
    f"sender_override = {_SENDER_ID_OVERRIDE or '(none)'}\n"
    f"looper_started = {_TALKER_LOOPER_STARTED}\n"
    f"delivery_worker = {worker_alive}\n"
    f"delivery_epoch = {delivery_epoch}\n"
    f"show_reasoning = {_SHOW_REASONING}\n"
    f"show_commands = {_SHOW_COMMANDS}"
  )

async def cmd_setagent(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)

  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  name = " ".join(context.args).strip().lower()
  if not name:
    await update.message.reply_text("Usage: /setagent <name>   (supported: looper)")
    return

  if name not in ("looper",):
    await update.message.reply_text(f"Unknown agent: {name}. Supported: looper")
    return

  global _CURRENT_AGENT
  _CURRENT_AGENT = name
  await update.message.reply_text(f"OK. current_agent = {_CURRENT_AGENT}")

async def cmd_reset_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  sender_id = _resolve_sender_id(update)
  try:
    async with _DELIVERY_SEND_LOCK:
      async with _SUBMIT_LOCK:
        # Reset ONLY current sender artifacts
        removed_files = _reset_sender_dir(sender_id)
        # Create signal to clear Looper memory state
        _create_reset_signal()
        
    await update.message.reply_text(
      f"OK. Session reset for {sender_id}. Removed files: {removed_files}"
    )
  except Exception as e:
    await update.message.reply_text(f"reset_session failed: {e}")

async def cmd_reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  try:
    async with _DELIVERY_SEND_LOCK:
      async with _SUBMIT_LOCK:
        sender_count, removed_files = _reset_all_sender_dirs()
        _create_reset_signal()
    await update.message.reply_text(
      f"OK. reset_all done. Sender dirs scanned: {sender_count}. Removed files: {removed_files}"
    )
  except Exception as e:
    await update.message.reply_text(f"reset_all failed: {e}")

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
  """Alias for /reset_session."""
  await cmd_reset_session(update, context)

async def cmd_loginstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)

  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  codex_path = _resolve_codex_path()
  cmd = [codex_path, "login", "status"]
  print(f"[RUN] loginstatus exec={cmd!r}")

  try:
    proc = await asyncio.create_subprocess_exec(
      *cmd,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE
    )
  except FileNotFoundError:
    await update.message.reply_text(f"Cannot find '{cmd[0]}' in PATH.")
    return

  try:
    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=60)
  except asyncio.TimeoutError:
    proc.kill()
    await update.message.reply_text("Timeout (60s). Killed.")
    return

  stdout = (stdout_b or b"").decode("utf-8", errors="replace").strip()
  stderr = (stderr_b or b"").decode("utf-8", errors="replace").strip()

  result = stdout if stdout else stderr
  if not result:
    result = f"exit_code={proc.returncode}"

  await update.message.reply_text(_clip(result))

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  
  help_text = """Available commands:
/id - show your chat_id
/agent - show gateway/looper state
/setagent <name> - set agent (supported: looper)
/reset_session - reset current sender queue/session
/reset_all - reset all sender queues
/reset - alias of /reset_session
/new_session - alias of /reset_session
/loginstatus - show Codex login status
/console - show current console mode
/setconsole quiet|full - set console output mode
/toggleconsole - toggle console mode
/show_reasoning on|off - enable/disable reasoning relay
/show_commands on|off - enable/disable command relay
/routing show|clear|set-user <SenderID> - pass routing command to Talker
/help - show this help

Notes:
- Requests are submitted immediately; results are delivered asynchronously by background worker.
- Plain text (without /) is also forwarded to current agent.
- Attachments are saved to Talker inbox sender folder (.../Inbox/<sender>/Files)."""
  
  await update.message.reply_text(help_text)

async def cmd_console(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  
  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return
  
  await update.message.reply_text(f"console_mode = {_CONSOLE_MODE}")

async def cmd_setconsole(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  
  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return
  
  mode = " ".join(context.args).strip().lower()
  if mode not in ("quiet", "full"):
    await update.message.reply_text("Usage: /setconsole quiet|full")
    return
  
  global _CONSOLE_MODE
  _CONSOLE_MODE = mode
  await update.message.reply_text(f"OK. console_mode = {_CONSOLE_MODE}")

async def cmd_toggleconsole(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  
  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return
  
  global _CONSOLE_MODE
  _CONSOLE_MODE = "full" if _CONSOLE_MODE == "quiet" else "quiet"
  await update.message.reply_text(f"OK. console_mode = {_CONSOLE_MODE}")

async def cmd_show_reasoning(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  global _SHOW_REASONING
  value, err = _parse_on_off_arg(context.args, command_name="show_reasoning")
  if err:
    await update.message.reply_text(err)
    return
  if value is None:
    _SHOW_REASONING = not _SHOW_REASONING
    await update.message.reply_text(f"OK. show_reasoning = {_SHOW_REASONING} (toggled)")
    return
  _SHOW_REASONING = value
  await update.message.reply_text(f"OK. show_reasoning = {_SHOW_REASONING}")

async def cmd_show_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  global _SHOW_COMMANDS
  value, err = _parse_on_off_arg(context.args, command_name="show_commands")
  if err:
    await update.message.reply_text(err)
    return
  if value is None:
    _SHOW_COMMANDS = not _SHOW_COMMANDS
    await update.message.reply_text(f"OK. show_commands = {_SHOW_COMMANDS} (toggled)")
    return
  _SHOW_COMMANDS = value
  await update.message.reply_text(f"OK. show_commands = {_SHOW_COMMANDS}")

async def cmd_routing(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)

  # Hard requirement: check chat permission before routing command processing.
  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  args_text = " ".join(context.args).strip()
  if not args_text:
    await update.message.reply_text(
      "Usage: /routing show | /routing clear | /routing set-user <SenderID>"
    )
    return

  routing_prompt = f"/routing {args_text}"
  marker = await _submit_prompt(update, routing_prompt, source="command:routing")
  if marker:
    await update.message.reply_text(f"Routing command submitted: {routing_prompt}")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
  # Any non-command text is treated as a prompt for the current agent.
  _echo_console(update)

  if not _is_allowed(update):
    # Still echo to console, but don't run anything.
    await update.message.reply_text("Access denied.")
    return

  text = update.message.text if update.message else ""
  await _submit_prompt(update, text, source="text")

async def _app_post_init(application: Application):
  _ensure_talker_paths()
  _bootstrap_delivery_state_to_tail()
  _append_run_log("DELIVERY_WORKER_START")
  await _start_delivery_worker(application)

async def _app_post_shutdown(application: Application):
  _append_run_log("DELIVERY_WORKER_STOP")
  await _stop_delivery_worker()

def main():
  print("[BOOT] Starting Telegram gateway (polling)...")
  print(f"[BOOT] Allowed chat_id = {ALLOWED_CHAT_ID_INT}")
  print(f"[BOOT] Current agent = {_CURRENT_AGENT}")
  print(f"[BOOT] Console mode = {_CONSOLE_MODE} (use /setconsole to change)")
  print(f"[BOOT] Looper root = {_LOOPER_ROOT}")
  print(f"[BOOT] Talker root = {_TALKER_ROOT}")
  print(f"[BOOT] Inbox root = {_TALKER_INBOX_ROOT}")
  if _SENDER_ID_OVERRIDE:
    print(f"[BOOT] Sender override = {_SENDER_ID_OVERRIDE}")
  print(f"[BOOT] Session storage: {_SESSION_DIR}/")

  if _SKIP_TALKER_BOOT:
    print("[BOOT] Talker looper startup skipped by GATEWAY_SKIP_TALKER_BOOT.")
  else:
    try:
      _ensure_talker_looper_started()
      print("[BOOT] Talker looper startup command sent.")
    except Exception as e:
      # Keep gateway alive. The next user message will retry and return actionable error to chat.
      print(f"[WARN] Talker looper start failed at boot: {e}")

  app = Application.builder().token(TOKEN).post_init(_app_post_init).post_shutdown(_app_post_shutdown).build()

  # Commands
  app.add_handler(CommandHandler("id", cmd_id))
  app.add_handler(CommandHandler("agent", cmd_agent))
  app.add_handler(CommandHandler("setagent", cmd_setagent))
  app.add_handler(CommandHandler("reset_session", cmd_reset_session))
  app.add_handler(CommandHandler("reset_all", cmd_reset_all))
  app.add_handler(CommandHandler("reset", cmd_reset))
  app.add_handler(CommandHandler("new_session", cmd_reset))
  app.add_handler(CommandHandler("loginstatus", cmd_loginstatus))
  app.add_handler(CommandHandler("help", cmd_help))
  app.add_handler(CommandHandler("console", cmd_console))
  app.add_handler(CommandHandler("setconsole", cmd_setconsole))
  app.add_handler(CommandHandler("toggleconsole", cmd_toggleconsole))
  app.add_handler(CommandHandler("show_reasoning", cmd_show_reasoning))
  app.add_handler(CommandHandler("show_commands", cmd_show_commands))
  app.add_handler(CommandHandler("routing", cmd_routing))

  # Any attachment (non-command) => save under sender Files directory
  app.add_handler(
    MessageHandler(
      (filters.ATTACHMENT | filters.PHOTO) & ~filters.COMMAND,
      on_file,
    )
  )

  # Any plain text (non-command) => run agent
  app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

  app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
  main()
