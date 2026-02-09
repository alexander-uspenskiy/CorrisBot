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
#   /reset              -> forget "resume --last" state (next message starts a fresh exec)
#   /loginstatus        -> show Codex login status (only for codex agent)
#   /help               -> list all available bot commands
#
# SECURITY:
#   Only ALLOWED_CHAT_ID can run agent commands (/run, plain text forwarding, /setagent, /reset).
#   /id is allowed for everyone (so you can discover chat_id), but is still echoed to console.

import os
import asyncio
import shutil
from typing import List, Optional
from datetime import datetime

from telegram import Update
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

# --- "Memory" flag for Codex exec resume --last ---
_CODEX_HAS_SESSION = False

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

def _agent_cmd(agent: str, prompt: str, output_path: Optional[str]) -> List[str]:
  # Keep this small & explicit. You can extend later (claude, etc.).
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
      return base + ["resume", "--last", prompt]

    # First message starts a fresh non-interactive session.
    return base + [prompt]

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

  cmd = _agent_cmd(_CURRENT_AGENT, prompt, out_file)
  print(f"[RUN] agent={_CURRENT_AGENT} exec={cmd!r}")

  await update.message.reply_text(f"Running on {_CURRENT_AGENT}…")

  try:
    proc = await asyncio.create_subprocess_exec(
      *cmd,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE
    )
  except FileNotFoundError:
    await update.message.reply_text(f"Cannot find '{cmd[0]}' in PATH. Try `{cmd[0]} --help` in terminal.")
    return

  try:
    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=300)  # 5 minutes
  except asyncio.TimeoutError:
    proc.kill()
    await update.message.reply_text("Timeout (300s). Killed.")
    print("[RUN] timeout -> killed")
    return

  stdout = (stdout_b or b"").decode("utf-8", errors="replace").strip()
  stderr = (stderr_b or b"").decode("utf-8", errors="replace").strip()

  print(f"[RUN] exit_code={proc.returncode} stdout_len={len(stdout)} stderr_len={len(stderr)}")
  _append_log(_STDOUT_LOG, stdout)
  _append_log(_STDERR_LOG, stderr)

  # If codex succeeded at least once, enable resume mode for future messages.
  if _CURRENT_AGENT == "codex" and proc.returncode == 0:
    _CODEX_HAS_SESSION = True

  # Prefer the "final assistant message" written by codex.
  final_msg = ""
  try:
    if os.path.exists(out_file):
      with open(out_file, "r", encoding="utf-8", errors="replace") as f:
        final_msg = f.read().strip()
  except Exception:
    final_msg = ""

  # 1) Send final message if present
  if final_msg:
    await update.message.reply_text(_clip(final_msg))
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
  _echo_console(update)

  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  global _CODEX_HAS_SESSION
  _CODEX_HAS_SESSION = False
  await update.message.reply_text("OK. Next message will start a fresh Codex exec (no resume).")

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
/reset - reset session memory (start fresh)
/loginstatus - show Codex login status
/help - show this help

Plain text (without /) is also forwarded to current agent."""
  
  await update.message.reply_text(help_text)

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
  print("[BOOT] Codex memory: ON after first successful run (uses `codex exec resume --last`).")
  print(f"[BOOT] Logs: {_STDOUT_LOG} / {_STDERR_LOG}")

  app = Application.builder().token(TOKEN).build()

  # Commands
  app.add_handler(CommandHandler("id", cmd_id))
  app.add_handler(CommandHandler("agent", cmd_agent))
  app.add_handler(CommandHandler("setagent", cmd_setagent))
  app.add_handler(CommandHandler("reset", cmd_reset))
  app.add_handler(CommandHandler("run", cmd_run))
  app.add_handler(CommandHandler("loginstatus", cmd_loginstatus))
  app.add_handler(CommandHandler("help", cmd_help))

  # Any plain text (non-command) => run agent
  app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

  app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
  main()
