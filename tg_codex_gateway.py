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
#   3) Gateway polls that result file and streams meaningful events back to Telegram.
#
# Setup:
#   1) Create a bot with @BotFather and get TELEGRAM_BOT_TOKEN
#   2) Discover your chat_id: set ALLOWED_CHAT_ID=0, run script, send /id
#   3) Set env vars:
#        - TELEGRAM_BOT_TOKEN
#        - ALLOWED_CHAT_ID   (your numeric chat_id)
#   4) Ensure Looper launcher exists (StartLoopsInWT.bat) and Codex login is valid
#
# Telegram commands:
#   /id                 -> show your chat_id
#   /agent              -> show current gateway/looper state
#   /setagent <name>    -> set current agent (supported: looper)
#   /run <text>         -> explicitly run text via current agent (same as plain text)
#   /reset_session      -> reset current sender queue/session
#   /reset_all          -> reset all sender queues
#   /reset              -> alias of /reset_session
#   /new_session        -> alias of /reset_session
#   /loginstatus        -> show Codex login status
#   /console            -> show current console output mode
#   /setconsole <mode>  -> set console mode: quiet (default) or full
#   /toggleconsole      -> toggle between quiet and full console mode
#   /help               -> list all available bot commands
#
# SECURITY:
#   Only ALLOWED_CHAT_ID can run agent commands (/run, plain text forwarding,
#   /setagent, /reset*).
#   /id is allowed for everyone (so you can discover chat_id), but is still echoed to console.

import os
import sys
import json
import time
import uuid
import atexit
import asyncio
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

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

# --- Looper/Talker configuration ---
_LOOPER_ROOT = os.environ.get("LOOPER_ROOT", r"C:\CorrisBot\Looper").strip() or r"C:\CorrisBot\Looper"
_TALKER_ROOT = os.environ.get("TALKER_ROOT", r"C:\CorrisBot\Talker").strip() or r"C:\CorrisBot\Talker"
_TALKER_INBOX_ROOT = os.path.join(_TALKER_ROOT, "Prompts", "Inbox")
_START_LOOPS_BAT = os.path.join(_LOOPER_ROOT, "StartLoopsInWT.bat")
_SENDER_ID_OVERRIDE = os.environ.get("TALKER_SENDER_ID", "").strip()

# Polling model (same style as looper: lightweight polling, no watchdog).
_RESULT_POLL_ACTIVE_SEC = float(os.environ.get("RESULT_POLL_ACTIVE_SEC", "0.25"))
_RESULT_POLL_IDLE_SEC = float(os.environ.get("RESULT_POLL_IDLE_SEC", "0.75"))
_RESULT_START_TIMEOUT_SEC = float(os.environ.get("RESULT_START_TIMEOUT_SEC", "120"))
_RESULT_TOTAL_TIMEOUT_SEC = float(os.environ.get("RESULT_TOTAL_TIMEOUT_SEC", "1800"))
_RESULT_FINISHED_IDLE_SEC = float(os.environ.get("RESULT_FINISHED_IDLE_SEC", "1.0"))

_PROMPT_TIMESTAMP_RE = re.compile(
  r"^(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})_"
  r"(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})_"
  r"(?P<millis>\d{3})(?:_(?P<suffix>[A-Za-z0-9]+))?$"
)

_TALKER_LOOPER_STARTED = False

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

# Ensure directory exists and load initial state
_ensure_session_dir()
_CURRENT_SESSION_DIR = _get_latest_session_dir()
if _CURRENT_SESSION_DIR is None:
  _create_new_session_dir()

# --- File delivery settings ---
_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB Telegram limit

# --- Concurrency protection ---
_RUN_LOCK = asyncio.Lock()
def _is_allowed(update: Update) -> bool:
  chat = update.effective_chat
  return bool(chat) and chat.id == ALLOWED_CHAT_ID_INT

def _clip(s: str, limit: int = 3500) -> str:
  # Telegram message limit is ~4096 chars; keep margin.
  if len(s) <= limit:
    return s
  return s[:limit] + "\n...(truncated)"

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

async def _typing_loop(chat, stop_event: asyncio.Event):
  """Send typing action every ~4 seconds until stop_event is set."""
  while not stop_event.is_set():
    try:
      await chat.send_action(ChatAction.TYPING)
    except Exception as e:
      print(f"[WARN] Failed to send typing action: {e}")
    try:
      await asyncio.wait_for(stop_event.wait(), timeout=4)
    except asyncio.TimeoutError:
      continue

async def _stop_typing_task(stop_event: asyncio.Event, task: asyncio.Task):
  """Stop typing loop and cleanup task."""
  stop_event.set()
  task.cancel()
  try:
    await task
  except asyncio.CancelledError:
    pass

def _process_looper_json_line(line: str, started_commands: Dict[str, bool]) -> Tuple[List[str], bool]:
  """
  Parse one JSON line from result stream.
  Returns (messages_to_emit, saw_turn_completed).
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
    messages.append(f"[command] {cmd} (in_progress)")
    return messages, saw_turn_completed

  if obj_type == "item.completed" and obj.get("item"):
    item = obj["item"]
    item_type = item.get("type")

    if item_type == "reasoning" and item.get("text"):
      messages.append(f"[reasoning] {item['text']}")
      return messages, saw_turn_completed

    if item_type == "agent_message" and item.get("text"):
      messages.append(f"[agent]\n{item['text']}")
      return messages, saw_turn_completed

    if item_type == "command_execution":
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

  if re.search(r"(error|failed)", obj_type, flags=re.IGNORECASE):
    messages.append(f"[error] {line}")

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

async def _deliver_files(update: Update, paths: List[str], base_dir: Optional[str] = None,
                         delivered_keys: Optional[Set[str]] = None):
  """
  Deliver files to Telegram chat.
  Paths can be absolute or relative (resolved to base_dir, then CWD).
  """
  for raw_path in paths:
    if os.path.isabs(raw_path):
      file_path = raw_path
    else:
      root = base_dir or os.getcwd()
      file_path = os.path.join(root, raw_path)

    file_path = os.path.normpath(file_path)
    key = file_path.lower()
    if delivered_keys is not None and key in delivered_keys:
      continue
    basename = os.path.basename(file_path)

    if not os.path.isfile(file_path):
      await update.message.reply_text(f"File not found: {raw_path}")
      continue

    try:
      file_size = os.path.getsize(file_path)
    except Exception as e:
      await update.message.reply_text(f"Failed to check size: {raw_path} ({e})")
      continue

    if file_size > _MAX_FILE_SIZE:
      await update.message.reply_text(f"File too large: {raw_path} ({file_size} bytes)")
      continue

    try:
      with open(file_path, "rb") as f:
        await update.message.reply_document(document=f, filename=basename, read_timeout=600, write_timeout=600)
      await update.message.reply_text(f"Sent: {basename} ({file_size} bytes)")
      if delivered_keys is not None:
        delivered_keys.add(key)
    except Exception as e:
      await update.message.reply_text(f"Failed to send: {raw_path} ({e})")

async def _emit_stream_messages(update: Update, messages: List[str], delivered_keys: Set[str]) -> bool:
  emitted = False
  for message in messages:
    clean_text, file_paths = _extract_deliver_files(message)
    if clean_text and clean_text.strip() != "[agent]":
      await update.message.reply_text(_clip(clean_text))
      emitted = True
    if file_paths:
      await _deliver_files(update, file_paths, base_dir=_TALKER_ROOT, delivered_keys=delivered_keys)
      emitted = True
  return emitted

async def _process_result_line(update: Update, line: str, started_commands: Dict[str, bool],
                               delivered_keys: Set[str]) -> Tuple[bool, bool, bool]:
  """
  Process one result file line.
  Returns (turn_completed, finished_line, emitted_anything).
  """
  trim = (line or "").strip()
  if not trim:
    return False, False, False

  # Ignore markdown framing lines produced by looper result writer.
  if trim.startswith("# Codex Result for ") or trim.startswith("Started: ") or trim.startswith("--- Fallback:"):
    return False, False, False

  if trim.startswith("{") and trim.endswith("}"):
    messages, turn_completed = _process_looper_json_line(trim, started_commands)
    emitted = await _emit_stream_messages(update, messages, delivered_keys)
    if _CONSOLE_MODE == "full":
      for msg in messages:
        print(f"[stream] {msg}")
    return turn_completed, False, emitted

  # Non-JSON informational lines.
  lowered = trim.lower()
  finished_line = trim.startswith("Finished:")
  messages = []
  if finished_line:
    messages.append(f"[done] {trim}")
  elif trim.startswith("Command failed with exit code:"):
    messages.append(f"[error] {trim}")
  elif re.search(r"\b(error|exception|failed|fatal)\b", lowered):
    messages.append(trim)
  elif re.search(r"\bwarn\b", lowered):
    messages.append(trim)

  emitted = await _emit_stream_messages(update, messages, delivered_keys)
  if _CONSOLE_MODE == "full":
    for msg in messages:
      print(f"[stream] {msg}")
  return False, finished_line, emitted

async def _stream_result_file(update: Update, result_path: str, session_stdout_path: Optional[str]) -> Tuple[bool, bool]:
  """
  Poll one result file and stream appended events.
  Returns (completed, emitted_any_output).
  """
  start_time = time.monotonic()
  last_change_time = start_time
  seen_file = False
  seen_turn_completed = False
  seen_finished_line = False
  emitted_any = False
  offset = 0
  pending = ""
  started_commands: Dict[str, bool] = {}
  delivered_keys: Set[str] = set()

  while True:
    now = time.monotonic()
    if os.path.isfile(result_path):
      seen_file = True
      try:
        with open(result_path, "r", encoding="utf-8", errors="replace") as f:
          f.seek(offset)
          chunk = f.read()
          offset = f.tell()
      except Exception:
        chunk = ""

      if chunk:
        last_change_time = now
        _append_raw(session_stdout_path, chunk)
        pending += chunk

        while True:
          nl = pending.find("\n")
          if nl < 0:
            break
          raw_line = pending[:nl].rstrip("\r")
          pending = pending[nl + 1:]

          turn_completed, finished_line, emitted = await _process_result_line(
            update, raw_line, started_commands, delivered_keys
          )
          seen_turn_completed = seen_turn_completed or turn_completed
          seen_finished_line = seen_finished_line or finished_line
          emitted_any = emitted_any or emitted
          # Fail-fast terminal state for looper hard failure line.
          if raw_line.strip().startswith("Command failed with exit code:"):
            return False, emitted_any

    if seen_turn_completed:
      if pending.strip():
        _, _, emitted = await _process_result_line(
          update, pending.rstrip("\r"), started_commands, delivered_keys
        )
        emitted_any = emitted_any or emitted
      return True, emitted_any

    if not seen_file:
      if now - start_time > _RESULT_START_TIMEOUT_SEC:
        await update.message.reply_text(f"Timeout waiting for result file ({int(_RESULT_START_TIMEOUT_SEC)}s).")
        return False, emitted_any
      await asyncio.sleep(max(0.05, _RESULT_POLL_IDLE_SEC))
      continue

    if seen_finished_line and (now - last_change_time) >= _RESULT_FINISHED_IDLE_SEC:
      if pending.strip():
        _, _, emitted = await _process_result_line(
          update, pending.rstrip("\r"), started_commands, delivered_keys
        )
        emitted_any = emitted_any or emitted
      return True, emitted_any

    if now - start_time > _RESULT_TOTAL_TIMEOUT_SEC:
      await update.message.reply_text(f"Timeout waiting for completion ({int(_RESULT_TOTAL_TIMEOUT_SEC)}s).")
      return False, emitted_any

    await asyncio.sleep(max(0.05, _RESULT_POLL_ACTIVE_SEC))

def _append_run_log(event: str, update: Update, prompt_len: int = 0, cmd: Optional[List[str]] = None,
                    exit_code: Optional[int] = None, timeout_killed: bool = False,
                    duration_ms: Optional[int] = None):
  """Append a line to the session run.log."""
  if not _CURRENT_SESSION_DIR:
    return
  try:
    run_log_path = os.path.join(_CURRENT_SESSION_DIR, "run.log")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = update.effective_user
    user_info = f"@{user.username}" if user and user.username else (user.full_name if user else "unknown")
    chat_id = update.effective_chat.id if update.effective_chat else 0
    session_name = os.path.basename(_CURRENT_SESSION_DIR)
    
    if event == "START":
      cmd_str = str(cmd) if cmd else "[]"
      line = f"{ts} START chat_id={chat_id} user={user_info} prompt_len={prompt_len} session={session_name} cmd={cmd_str}\n"
    elif event == "END":
      line = f"{ts} END chat_id={chat_id} exit={exit_code} timeout_killed={timeout_killed} duration_ms={duration_ms}\n"
    else:
      line = f"{ts} {event} chat_id={chat_id}\n"
    
    with open(run_log_path, "a", encoding="utf-8") as f:
      f.write(line)
  except Exception:
    pass

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
  return _clear_sender_artifacts(sender_dir)

def _reset_all_sender_dirs() -> Tuple[int, int]:
  _validate_reset_scope()
  _ensure_talker_paths()
  sender_count = 0
  removed_files = 0
  for name in os.listdir(_TALKER_INBOX_ROOT):
    path = os.path.join(_TALKER_INBOX_ROOT, name)
    if not os.path.isdir(path):
      continue
    sender_count += 1
    removed_files += _clear_sender_artifacts(path)
  return sender_count, removed_files

async def _run_agent(update: Update, prompt: str):
  global _CURRENT_AGENT, _CURRENT_SESSION_DIR

  prompt = (prompt or "").strip()
  if not prompt:
    await update.message.reply_text("Empty prompt.")
    return

  # Concurrency protection: non-blocking acquire.
  try:
    await asyncio.wait_for(_RUN_LOCK.acquire(), timeout=0.001)
  except asyncio.TimeoutError:
    await update.message.reply_text("Busy. Try again in a moment.")
    return

  if _CURRENT_SESSION_DIR is None:
    _create_new_session_dir()

  run_start_time = datetime.now()
  completed = False
  timeout_killed = False
  session_stderr_path: Optional[str] = None

  stop_typing = asyncio.Event()
  typing_task = asyncio.create_task(_typing_loop(update.effective_chat, stop_typing))

  try:
    try:
      await asyncio.to_thread(_ensure_talker_looper_started)
    except Exception as e:
      await update.message.reply_text(f"Failed to start Talker looper: {e}")
      return

    session_stdout_path, session_stderr_path = _get_session_log_paths()
    if not session_stdout_path or not session_stderr_path:
      session_stdout_path = os.path.join(os.getcwd(), "_temp_stdout.log")
      session_stderr_path = os.path.join(os.getcwd(), "_temp_stderr.log")

    sender_id = _resolve_sender_id(update)
    sender_dir = os.path.join(_TALKER_INBOX_ROOT, sender_id)
    marker, prompt_path, result_path = _allocate_prompt_paths(sender_dir)
    _write_prompt_atomic(prompt_path, prompt)

    run_cmd = ["looper_publish", f"sender={sender_id}", prompt_path]
    print(
      f"[RUN] agent={_CURRENT_AGENT} mode={_CONSOLE_MODE} "
      f"session={os.path.basename(_CURRENT_SESSION_DIR or 'none')} marker={marker} sender={sender_id}"
    )
    _append_run_log("START", update, len(prompt), run_cmd)

    _append_raw(session_stdout_path, f"\n=== Prompt marker: {marker} sender={sender_id} ===\n")
    _append_raw(session_stdout_path, f"Prompt file: {prompt_path}\n")
    _append_raw(session_stdout_path, f"Result file: {result_path}\n")

    completed, emitted_any = await _stream_result_file(update, result_path, session_stdout_path)
    if not emitted_any and completed:
      await update.message.reply_text("Done.")
    if not completed:
      timeout_killed = True
      _append_raw(session_stderr_path, f"[WARN] Stream did not complete for marker={marker}\n")
  except Exception as e:
    _append_raw(session_stderr_path, f"[ERROR] _run_agent failed: {e}\n")
    await update.message.reply_text(f"Run failed: {e}")
  finally:
    await _stop_typing_task(stop_typing, typing_task)
    duration_ms = int((datetime.now() - run_start_time).total_seconds() * 1000)
    exit_code = 0 if completed else 1
    _append_run_log(
      "END",
      update,
      exit_code=exit_code,
      timeout_killed=timeout_killed,
      duration_ms=duration_ms,
    )
    _RUN_LOCK.release()

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
  await update.message.reply_text(
    f"current_agent = {_CURRENT_AGENT}\n"
    f"looper_root = {_LOOPER_ROOT}\n"
    f"talker_root = {_TALKER_ROOT}\n"
    f"inbox_root = {_TALKER_INBOX_ROOT}\n"
    f"sender_id = {sender_id}\n"
    f"sender_override = {_SENDER_ID_OVERRIDE or '(none)'}\n"
    f"looper_started = {_TALKER_LOOPER_STARTED}"
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
  if _RUN_LOCK.locked():
    await update.message.reply_text("Busy. Try again in a moment.")
    return

  sender_id = _resolve_sender_id(update)
  try:
    removed = _reset_sender_dir(sender_id)
    await update.message.reply_text(
      f"OK. reset_session done for sender: {sender_id}. Removed files: {removed}"
    )
  except Exception as e:
    await update.message.reply_text(f"reset_session failed: {e}")

async def cmd_reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return
  if _RUN_LOCK.locked():
    await update.message.reply_text("Busy. Try again in a moment.")
    return

  try:
    sender_count, removed_files = _reset_all_sender_dirs()
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
/run <text> - run text via current agent
/reset_session - reset current sender queue/session
/reset_all - reset all sender queues
/reset - alias of /reset_session
/new_session - alias of /reset_session
/loginstatus - show Codex login status
/console - show current console mode
/setconsole quiet|full - set console output mode
/toggleconsole - toggle console mode
/help - show this help

Notes:
- Only one run at a time; if busy, you'll get "Busy. Try again in a moment."
- Plain text (without /) is also forwarded to current agent."""
  
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

async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)

  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  prompt = " ".join(context.args).strip()
  if not prompt:
    await update.message.reply_text("Usage: /run <text>")
    return

  await _run_agent(update, prompt)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
  # Any non-command text is treated as a prompt for the current agent.
  _echo_console(update)

  if not _is_allowed(update):
    # Still echo to console, but don't run anything.
    await update.message.reply_text("Access denied.")
    return

  text = update.message.text if update.message else ""
  await _run_agent(update, text)

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

  try:
    _ensure_talker_looper_started()
    print("[BOOT] Talker looper startup command sent.")
  except Exception as e:
    # Keep gateway alive. /run will retry and return actionable error to chat.
    print(f"[WARN] Talker looper start failed at boot: {e}")

  app = Application.builder().token(TOKEN).build()

  # Commands
  app.add_handler(CommandHandler("id", cmd_id))
  app.add_handler(CommandHandler("agent", cmd_agent))
  app.add_handler(CommandHandler("setagent", cmd_setagent))
  app.add_handler(CommandHandler("reset_session", cmd_reset_session))
  app.add_handler(CommandHandler("reset_all", cmd_reset_all))
  app.add_handler(CommandHandler("reset", cmd_reset))
  app.add_handler(CommandHandler("new_session", cmd_reset))
  app.add_handler(CommandHandler("run", cmd_run))
  app.add_handler(CommandHandler("loginstatus", cmd_loginstatus))
  app.add_handler(CommandHandler("help", cmd_help))
  app.add_handler(CommandHandler("console", cmd_console))
  app.add_handler(CommandHandler("setconsole", cmd_setconsole))
  app.add_handler(CommandHandler("toggleconsole", cmd_toggleconsole))

  # Any plain text (non-command) => run agent
  app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

  app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
  main()
