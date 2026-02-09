#!/usr/bin/env python3
# tg_codex_gateway.py
# Telegram -> Agent CLI gateway (default: Codex CLI)
#
# Behavior:
#   - Echo ALL incoming text messages to the console.
#   - Bot commands (start with /) are handled by this script.
#   - Any non-command text is forwarded to the CURRENT agent (default: "codex").
#
# Codex CLI behavior tweaks:
#   1) Only send the assistant's FINAL message back to Telegram
#      using `--output-last-message/-o` (so no CLI headers in Telegram).
#   2) Keep "memory" across messages by resuming the last exec thread:
#         first run:  codex exec ...
#         next runs:  codex exec resume --last ...
#   3) Log full stdout/stderr to console and to local log files for debugging.
#
# Setup:
#   1) Create a bot with @BotFather and get TELEGRAM_BOT_TOKEN
#   2) Discover your chat_id: set ALLOWED_CHAT_ID=0, run script, send /id
#   3) Set env vars:
#        - TELEGRAM_BOT_TOKEN
#        - ALLOWED_CHAT_ID   (your numeric chat_id)
#   4) Ensure Codex CLI is installed and available (try: codex --help)
#
# Telegram commands:
#   /id                 -> show your chat_id
#   /agent              -> show current agent name + whether resume memory is on
#   /setagent <name>    -> set current agent (supported: codex)
#   /run <text>         -> explicitly run text via current agent (same as plain text)
#   /reset              -> start a fresh session (new file, no resume)
#   /new_session        -> same as /reset
#   /loginstatus        -> show Codex login status (only for codex agent)
#   /console            -> show current console output mode
#   /setconsole <mode>  -> set console mode: quiet (default) or full
#   /toggleconsole      -> toggle between quiet and full console mode
#   /help               -> list all available bot commands
#
# SECURITY:
#   Only ALLOWED_CHAT_ID can run agent commands (/run, plain text forwarding, /setagent, /reset).
#   /id is allowed for everyone (so you can discover chat_id), but is still echoed to console.

import os
import asyncio
import re
import shutil
from typing import List, Optional, Tuple
from datetime import datetime

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

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

# --- Agent selection (in-memory). Default is Codex CLI. ---
_CURRENT_AGENT = "codex"

# --- Session persistence for Codex exec resume --last ---
_SESSION_DIR = os.path.join(os.getcwd(), "sessions")
_CURRENT_SESSION_FILE = None  # Path to current active session file

def _ensure_session_dir():
  """Create sessions directory if it doesn't exist."""
  try:
    os.makedirs(_SESSION_DIR, exist_ok=True)
  except Exception:
    pass

def _get_latest_session_file() -> Optional[str]:
  """Get the most recent session file path, or None if no sessions exist."""
  try:
    if os.path.isdir(_SESSION_DIR):
      files = [f for f in os.listdir(_SESSION_DIR) if f.startswith("codex_session_")]
      if files:
        # Sort by filename (timestamp) to get latest
        files.sort()
        return os.path.join(_SESSION_DIR, files[-1])
  except Exception:
    pass
  return None

def _create_new_session_file():
  """Create a new session file (called by /reset or /new_session)."""
  global _CURRENT_SESSION_FILE
  try:
    _ensure_session_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _CURRENT_SESSION_FILE = os.path.join(_SESSION_DIR, f"codex_session_{timestamp}.txt")
    with open(_CURRENT_SESSION_FILE, "w") as f:
      f.write(f"Session started at {timestamp}\n")
  except Exception:
    _CURRENT_SESSION_FILE = None

def _append_to_session(note: str):
  """Append a note to current session file."""
  if _CURRENT_SESSION_FILE:
    try:
      with open(_CURRENT_SESSION_FILE, "a") as f:
        f.write(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}: {note}\n")
    except Exception:
      pass

# Ensure directory exists and load initial state
_ensure_session_dir()
_CURRENT_SESSION_FILE = _get_latest_session_file()
_CODEX_HAS_SESSION = _CURRENT_SESSION_FILE is not None

# --- Console output mode: "quiet" (default) or "full" ---
_CONSOLE_MODE = "full"

# --- File delivery settings ---
_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB Telegram limit

# --- Logging ---
_LOG_STEM = os.path.join(os.getcwd(), "tg_codex_gateway")
_STDERR_LOG = _LOG_STEM + "_stderr.log"
_STDOUT_LOG = _LOG_STEM + "_stdout.log"

def _is_allowed(update: Update) -> bool:
  chat = update.effective_chat
  return bool(chat) and chat.id == ALLOWED_CHAT_ID_INT

def _clip(s: str, limit: int = 3500) -> str:
  # Telegram message limit is ~4096 chars; keep margin.
  if len(s) <= limit:
    return s
  return s[:limit] + "\n…(truncated)"

def _echo_console(update: Update):
  chat = update.effective_chat
  user = update.effective_user
  chat_id = chat.id if chat else None
  username = (user.username if user else None) or ""
  name = (user.full_name if user else None) or ""
  text = update.message.text if update.message else ""
  print(f"[TG] chat_id={chat_id} user={name} @{username} text={text!r}")

def _append_log(path: str, text: str):
  if not text:
    return
  ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  with open(path, "a", encoding="utf-8", errors="replace") as f:
    f.write(f"\n===== {ts} =====\n")
    f.write(text)
    f.write("\n")


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

async def _pump_stream(stream, prefix: str, log_path: str, mode: str, stop_event: asyncio.Event, collector: list, buf_size: int = 10):
  """Pump lines from stream to console (if full mode) and log file (buffered)."""
  buffer = []
  while not stop_event.is_set():
    try:
      line_b = await asyncio.wait_for(stream.readline(), timeout=0.5)
      if not line_b:
        break
      line = line_b.decode("utf-8", errors="replace").rstrip("\n\r")
      collector.append(line)
      if mode == "full":
        print(f"{prefix}{line}")
      buffer.append(line)
      if len(buffer) >= buf_size:
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
          f.write("\n".join(buffer) + "\n")
        buffer.clear()
    except asyncio.TimeoutError:
      continue
    except asyncio.CancelledError:
      break
    except Exception as e:
      print(f"[WARN] Pump error: {e}")
      break
  # Flush remaining buffer
  if buffer:
    with open(log_path, "a", encoding="utf-8", errors="replace") as f:
      f.write("\n".join(buffer) + "\n")

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

async def _deliver_files(update: Update, paths: List[str]):
  """
  Deliver files to Telegram chat.
  Paths can be absolute or relative (resolved to WORKDIR).
  """
  for raw_path in paths:
    # Resolve path
    if os.path.isabs(raw_path):
      file_path = raw_path
    else:
      file_path = os.path.join(os.getcwd(), raw_path)
    
    file_path = os.path.normpath(file_path)
    basename = os.path.basename(file_path)
    
    # Check file exists
    if not os.path.isfile(file_path):
      await update.message.reply_text(f"File not found: {raw_path}")
      continue
    
    # Check file size
    try:
      file_size = os.path.getsize(file_path)
    except Exception as e:
      await update.message.reply_text(f"Failed to check size: {raw_path} ({e})")
      continue
    
    if file_size > _MAX_FILE_SIZE:
      await update.message.reply_text(f"File too large: {raw_path} ({file_size} bytes)")
      continue
    
    # Send file (with extended timeout for large files)
    try:
      with open(file_path, "rb") as f:
        await update.message.reply_document(document=f, filename=basename, read_timeout=600, write_timeout=600)
      await update.message.reply_text(f"Sent: {basename} ({file_size} bytes)")
    except Exception as e:
      await update.message.reply_text(f"Failed to send: {raw_path} ({e})")

def _agent_cmd(agent: str, output_path: Optional[str]) -> List[str]:
  # Keep this small & explicit. You can extend later (claude, etc.).
  # Note: prompt is passed via stdin, not as command-line argument (to support multiline).
  agent = (agent or "").strip().lower()
  if agent == "codex":
    codex_path = _resolve_codex_path()

    # Always skip git repo check (your C:\CorrisBot may not be a git repo).
    base = [codex_path, "exec", "--skip-git-repo-check"]

    # Write assistant final message to a file (so we don't ship CLI headers to Telegram).
    if output_path:
      base += ["--output-last-message", output_path]

    global _CODEX_HAS_SESSION
    if _CODEX_HAS_SESSION:
      # Continue the last non-interactive session in this working directory.
      # Docs: codex exec resume --last "follow-up"
      # Note: "-" tells codex to read prompt from stdin
      return base + ["resume", "--last", "-"]

    # First message starts a fresh non-interactive session.
    # Note: "-" tells codex to read prompt from stdin
    return base + ["-"]

  raise ValueError(f"Unknown agent: {agent}")

async def _run_agent(update: Update, prompt: str):
  global _CURRENT_AGENT, _CODEX_HAS_SESSION

  prompt = (prompt or "").strip()
  if not prompt:
    await update.message.reply_text("Empty prompt.")
    return

  # A per-run output file for the "final assistant message"
  out_file = os.path.join(os.getcwd(), "_tg_last_message.txt")
  try:
    if os.path.exists(out_file):
      os.remove(out_file)
  except Exception:
    pass

  cmd = _agent_cmd(_CURRENT_AGENT, out_file)
  print(f"[RUN] agent={_CURRENT_AGENT} mode={_CONSOLE_MODE} exec={cmd!r}")

  # Start typing indicator loop
  stop_typing = asyncio.Event()
  typing_task = asyncio.create_task(_typing_loop(update.effective_chat, stop_typing))

  proc = None
  stdout_lines = []
  stderr_lines = []
  stop_pump = asyncio.Event()
  stdout_task = None
  stderr_task = None
  try:
    proc = await asyncio.create_subprocess_exec(
      *cmd,
      stdin=asyncio.subprocess.PIPE,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE
    )

    # Start pump tasks for streaming output
    stdout_task = asyncio.create_task(_pump_stream(proc.stdout, "[codex:out] ", _STDOUT_LOG, _CONSOLE_MODE, stop_pump, stdout_lines))
    stderr_task = asyncio.create_task(_pump_stream(proc.stderr, "[codex:err] ", _STDERR_LOG, _CONSOLE_MODE, stop_pump, stderr_lines))

    # Send prompt via stdin (supports multiline), then wait for process
    try:
      proc.stdin.write(prompt.encode("utf-8"))
      await proc.stdin.drain()
      proc.stdin.close()
      await asyncio.wait_for(proc.wait(), timeout=600)  # 10 minutes
    except asyncio.TimeoutError:
      proc.kill()
      stop_pump.set()
      for task in (stdout_task, stderr_task):
        task.cancel()
        try:
          await task
        except asyncio.CancelledError:
          pass
      await update.message.reply_text("Timeout (600s). Killed.")
      print("[RUN] timeout (600s) -> killed")
      return

    # Stop pump tasks
    stop_pump.set()
    for task in (stdout_task, stderr_task):
      task.cancel()
      try:
        await task
      except asyncio.CancelledError:
        pass

  except FileNotFoundError:
    await update.message.reply_text(f"Cannot find '{cmd[0]}' in PATH. Try `{cmd[0]} --help` in terminal.")
    return
  finally:
    await _stop_typing_task(stop_typing, typing_task)

  # Use collected output for Telegram response
  stdout = "\n".join(stdout_lines)
  stderr = "\n".join(stderr_lines)

  print(f"[RUN] exit_code={proc.returncode} stdout_len={len(stdout)} stderr_len={len(stderr)}")

  # If codex succeeded at least once, enable resume mode for future messages.
  if _CURRENT_AGENT == "codex" and proc.returncode == 0:
    global _CODEX_HAS_SESSION
    _CODEX_HAS_SESSION = True
    _append_to_session(f"Run successful, exit_code={proc.returncode}")

  # Prefer the "final assistant message" written by codex.
  final_msg = ""
  try:
    if os.path.exists(out_file):
      with open(out_file, "r", encoding="utf-8", errors="replace") as f:
        final_msg = f.read().strip()
  except Exception:
    final_msg = ""

  # 1) Process final message: extract file delivery directives and send clean text
  if final_msg:
    clean_text, file_paths = _extract_deliver_files(final_msg)
    if clean_text:
      await update.message.reply_text(_clip(clean_text))
    # Deliver files if any directives found
    if file_paths:
      await _deliver_files(update, file_paths)
  else:
    # Fallback: if no out_file produced anything, use stdout (usually still cleaner than stderr)
    if stdout:
      await update.message.reply_text(_clip(stdout))

  # 2) Only surface stderr to Telegram when something failed.
  if proc.returncode != 0 and stderr:
    await update.message.reply_text("stderr:\n" + _clip(stderr))

  # 3) If absolutely nothing came out, at least report exit code.
  if not final_msg and not stdout and (proc.returncode == 0) and not stderr:
    await update.message.reply_text(f"Done. exit_code={proc.returncode}")

# --- Telegram handlers ---

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  chat = update.effective_chat
  if not chat:
    return
  await update.message.reply_text(f"chat_id = {chat.id}")

async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  mem = "on" if (_CURRENT_AGENT == "codex" and _CODEX_HAS_SESSION) else "off"
  await update.message.reply_text(f"current_agent = {_CURRENT_AGENT}\nresume_memory = {mem}")

async def cmd_setagent(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)

  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  name = " ".join(context.args).strip().lower()
  if not name:
    await update.message.reply_text("Usage: /setagent <name>   (supported: codex)")
    return

  # Validate by trying to build a command.
  try:
    _agent_cmd(name, "ping", None)
  except Exception:
    await update.message.reply_text(f"Unknown agent: {name}. Supported: codex")
    return

  global _CURRENT_AGENT
  _CURRENT_AGENT = name
  await update.message.reply_text(f"OK. current_agent = {_CURRENT_AGENT}")

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
  """Start a fresh session (synonym: /new_session)."""
  _echo_console(update)

  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  global _CODEX_HAS_SESSION
  _CODEX_HAS_SESSION = False
  _create_new_session_file()
  await update.message.reply_text("OK. New session started. Next run will be fresh (no resume).")

async def cmd_loginstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)

  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  if _CURRENT_AGENT != "codex":
    await update.message.reply_text(f"Command only available for 'codex' agent. Current: {_CURRENT_AGENT}")
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
/agent - show current agent and memory status
/setagent <name> - set agent (supported: codex)
/run <text> - run text via current agent
/reset - start a fresh session (no resume)
/new_session - same as /reset
/loginstatus - show Codex login status
/console - show current console mode
/setconsole quiet|full - set console output mode
/toggleconsole - toggle console mode
/help - show this help

Plain text (without /) is also forwarded to current agent."""
  
  await update.message.reply_text(help_text)

async def cmd_console(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
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
  print("[BOOT] Starting Telegram gateway (polling)…")
  print(f"[BOOT] Allowed chat_id = {ALLOWED_CHAT_ID_INT}")
  print(f"[BOOT] Current agent = {_CURRENT_AGENT}")
  print(f"[BOOT] Console mode = {_CONSOLE_MODE} (use /setconsole to change)")
  print("[BOOT] Codex memory: ON after first successful run (uses `codex exec resume --last`).")
  print(f"[BOOT] Logs: {_STDOUT_LOG} / {_STDERR_LOG}")

  app = Application.builder().token(TOKEN).build()

  # Commands
  app.add_handler(CommandHandler("id", cmd_id))
  app.add_handler(CommandHandler("agent", cmd_agent))
  app.add_handler(CommandHandler("setagent", cmd_setagent))
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
